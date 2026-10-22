import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from packages.config import Settings
from packages.documents.models import Document, DocumentVersion
from packages.documents.service import DocumentService
from packages.documents.validation import validate_upload
from packages.identity.models import User, UserRole
from packages.identity.organization import load_actor
from packages.identity.security import hash_password
from packages.processing.models import ProcessingJob
from packages.processing.service import dispatch_pending, process_job
from packages.storage import S3Storage

pytestmark = pytest.mark.infrastructure


def test_concurrent_versions_use_separate_connections_and_keep_originals(
    concurrent_db: sessionmaker[Session],
) -> None:
    storage = S3Storage(Settings())
    with concurrent_db() as db:
        user = User(
            email="concurrent@documind.example",
            display_name="Concurrent fixture",
            password_hash=hash_password("ConcurrentFixture2026!"),
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_name="KNOWLEDGE_MANAGER"))
        db.commit()
        actor = load_actor(db, user)
        document, first = DocumentService(db, actor, storage).create(
            validate_upload("first.txt", b"first original", Settings())
        )
        document_id, first_key = document.id, first.object_key
    gate = Barrier(2)

    def add(content: bytes) -> int:
        with concurrent_db() as db:
            gate.wait(timeout=10)
            _, version = DocumentService(db, actor, storage).new_version(
                document_id, validate_upload("new.txt", content, Settings())
            )
            return version.version_number

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            numbers = list(executor.map(add, [b"concurrent two", b"concurrent three"]))
        assert sorted(numbers) == [2, 3]
        assert storage.get(first_key) == b"first original"
        with concurrent_db() as db:
            versions = list(
                db.scalars(
                    select(DocumentVersion).where(DocumentVersion.document_id == document_id)
                )
            )
            assert len({version.object_key for version in versions}) == 3
            assert {version.status for version in versions} == {"UPLOADED"}
            jobs = list(
                db.scalars(
                    select(ProcessingJob)
                    .join(DocumentVersion)
                    .where(DocumentVersion.document_id == document_id)
                )
            )
            assert len(jobs) == len({job.version_id for job in jobs}) == 3

        # Two dispatchers compete for the same committed row; only one may publish it.
        sent: list[UUID] = []
        entered, release = Event(), Event()

        def publish(job_id: UUID) -> None:
            sent.append(job_id)
            entered.set()
            assert release.wait(timeout=10)

        def dispatch() -> dict[str, int]:
            with concurrent_db() as db:
                return dispatch_pending(db, publish, only_job_ids=(jobs[0].id,))

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_dispatch = executor.submit(dispatch)
            assert entered.wait(timeout=10)
            try:
                competing = executor.submit(dispatch).result(timeout=10)
                assert competing["queued"] == 0
            finally:
                release.set()
            assert first_dispatch.result(timeout=10)["queued"] == 1
        assert sent == [jobs[0].id]
    finally:
        with concurrent_db() as db:
            keys = list(
                db.scalars(
                    select(DocumentVersion.object_key).where(
                        DocumentVersion.document_id == document_id
                    )
                )
            )
        for key in keys:
            storage.delete(key)


def test_published_message_survives_dispatch_commit_interruption(
    concurrent_db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with concurrent_db() as db:
        user = User(
            email="interrupted@documind.example",
            display_name="Interrupted fixture",
            password_hash=hash_password("ConcurrentFixture2026!"),
        )
        db.add(user)
        db.flush()

        document = Document(owner_id=user.id, title="Dispatch metadata fixture")
        db.add(document)
        db.flush()

        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            uploaded_by=user.id,
            filename="fixture.txt",
            media_type="text/plain",
            size_bytes=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
            object_key=f"test-not-stored/{document.id}",
            status="UPLOADED",
        )
        db.add(version)
        db.flush()
        job = ProcessingJob(version_id=version.id, pipeline_key="text-v1")
        db.add(job)
        db.commit()
        job_id = job.id
    sent: list[UUID] = []
    with concurrent_db() as db:

        def interrupted() -> None:
            raise SQLAlchemyError("simulated commit interruption")

        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", interrupted)
            with pytest.raises(SQLAlchemyError):
                dispatch_pending(db, sent.append, only_job_ids=(job_id,))
        db.rollback()
    assert sent == [job_id]
    with concurrent_db() as db:
        assert process_job(db, job_id) == "FAILED"
        assert process_job(db, job_id) == "FAILED"
        stored = db.get(ProcessingJob, job_id)
        assert stored and stored.attempts == 1 and stored.error_code == "STORAGE_READ_FAILED"
