"""Actual Redis/Celery delivery with committed PostgreSQL metadata and a private test queue."""

import hashlib
import os
from uuid import UUID, uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from sqlalchemy import delete
from sqlalchemy.orm import Session

from apps.worker.celery_app import create_celery_app
from apps.worker.processing import process_document
from packages.config import Settings
from packages.database import make_engine
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.security import hash_password
from packages.processing.enqueue import ensure_job
from packages.processing.models import ProcessingJob
from packages.processing.service import dispatch_pending

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.skipif(os.getenv("DOCUMIND_TEST_INFRA") != "1", reason="requires Compose services"),
]


def test_real_redis_delivery_leaves_real_job_pending_without_retry_loop() -> None:
    settings = Settings()
    engine = make_engine(settings)
    user_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    application = create_celery_app(settings)
    queue = f"documind-tests-{uuid4().hex}"
    application.conf.task_default_queue = queue
    application.task(name="documind.process_document")(process_document)
    task_ids: list[str] = []

    def publish(job_id: UUID) -> None:
        result = application.send_task(
            "documind.process_document", args=[str(job_id)], queue=queue, retry=False
        )
        task_ids.append(str(result.id))

    try:
        with Session(engine, expire_on_commit=False) as db:
            db.add(
                User(
                    id=user_id,
                    email=f"job-{user_id}@documind.example",
                    display_name="Synthetic queue test",
                    password_hash=hash_password("SyntheticQueueOnly2026!"),
                )
            )
            db.flush()
            db.add(Document(id=document_id, owner_id=user_id, title="Queue metadata fixture"))
            db.flush()
            # The worker currently tests orchestration only and does not access object storage.
            db.add(
                DocumentVersion(
                    id=version_id,
                    document_id=document_id,
                    version_number=1,
                    uploaded_by=user_id,
                    filename="fixture.txt",
                    media_type="text/plain",
                    size_bytes=1,
                    sha256=hashlib.sha256(b"x").hexdigest(),
                    object_key=f"test-queue/{version_id}",
                    status="UPLOADED",
                )
            )
            db.flush()
            job = ensure_job(db, version_id, "text-v1")
            db.commit()
            job_id = job.id
        with start_worker(application, pool="solo", perform_ping_check=False, shutdown_timeout=10):
            with Session(engine, expire_on_commit=False) as db:
                assert dispatch_pending(db, publish, only_job_ids=(job_id,))["queued"] == 1
            assert application.AsyncResult(task_ids[0]).get(timeout=10) == {
                "status": "WAITING_PIPELINE"
            }
            # A duplicate broker message is harmless and consumes no processing attempt.
            publish(job_id)
            assert application.AsyncResult(task_ids[1]).get(timeout=10) == {
                "status": "WAITING_PIPELINE"
            }
        with Session(engine) as db:
            stored = db.get(ProcessingJob, job_id)
            version = db.get(DocumentVersion, version_id)
            assert stored and stored.status == "WAITING_PIPELINE" and stored.attempts == 0
            assert version and version.status == "QUEUED"
            assert dispatch_pending(db, publish, only_job_ids=(job_id,))["queued"] == 0
    finally:
        for task_id in task_ids:
            application.AsyncResult(task_id).forget()
        with application.connection_for_write() as connection:
            connection.default_channel.queue_delete(queue=queue)
        application.close()
        with Session(engine) as db:
            db.execute(delete(ProcessingJob).where(ProcessingJob.version_id == version_id))
            db.execute(delete(DocumentVersion).where(DocumentVersion.id == version_id))
            db.execute(delete(Document).where(Document.id == document_id))
            db.execute(delete(User).where(User.id == user_id))
            db.commit()
        engine.dispose()
