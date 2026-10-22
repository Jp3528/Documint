"""Actual Redis/Celery delivery with committed PostgreSQL metadata and a private test queue."""

import hashlib
import os
from uuid import UUID, uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.celery_app import create_celery_app
from apps.worker.processing import process_document
from packages.config import Settings
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.security import hash_password
from packages.indexing.models import ChunkEmbedding, IndexRevision
from packages.processing.enqueue import ensure_job
from packages.processing.models import ProcessingJob
from packages.processing.service import dispatch_pending
from packages.storage import S3Storage

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.skipif(os.getenv("DOCUMIND_TEST_INFRA") != "1", reason="requires Compose services"),
]


def test_real_redis_delivery_completes_index_once(
    concurrent_db: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(embedding_provider="fake")
    engine = concurrent_db.kw["bind"]
    # Same PostgreSQL/worker code, directed to this test's committed disposable schema.
    monkeypatch.setattr("apps.worker.processing.make_engine", lambda _: engine)
    monkeypatch.setattr("apps.worker.processing.get_settings", lambda: settings)
    user_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    application = create_celery_app(settings)
    queue = f"documind-tests-{uuid4().hex}"
    application.conf.task_default_queue = queue
    application.task(name="documind.process_document")(process_document)
    task_ids: list[str] = []
    storage = S3Storage(settings)
    storage.put(f"test-queue/{version_id}", b"x", "text/plain")

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
            assert application.AsyncResult(task_ids[0]).get(timeout=10) == {"status": "SUCCEEDED"}
            # Duplicate delivery neither calls the provider nor consumes another attempt.
            publish(job_id)
            assert application.AsyncResult(task_ids[1]).get(timeout=10) == {"status": "SUCCEEDED"}
        with Session(engine) as db:
            stored = db.get(ProcessingJob, job_id)
            version = db.get(DocumentVersion, version_id)
            assert stored and stored.status == "SUCCEEDED" and stored.attempts == 1
            assert version and version.status == "READY"
            revision = db.get(IndexRevision, stored.index_revision_id)
            assert revision and revision.embedding_profile["mode"] == "FAKE"
            assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 1
            assert dispatch_pending(db, publish, only_job_ids=(job_id,))["queued"] == 0
    finally:
        for task_id in task_ids:
            application.AsyncResult(task_id).forget()
        with application.connection_for_write() as connection:
            connection.default_channel.queue_delete(queue=queue)
        application.close()
        storage.delete(f"test-queue/{version_id}")
