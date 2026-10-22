import hashlib
import logging
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_session
from apps.api.main import create_app
from packages.config import Settings
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User, UserRole
from packages.identity.security import hash_password, utcnow
from packages.processing.enqueue import ensure_job
from packages.processing.models import ProcessingJob
from packages.processing.service import dispatch_pending, process_job

pytestmark = pytest.mark.infrastructure


@dataclass
class JobHarness:
    factory: sessionmaker[Session]
    client: TestClient
    headers: dict[str, dict[str, str]]
    document_id: UUID
    version_id: UUID
    job_id: UUID


@pytest.fixture
def jobs(isolated_db: sessionmaker[Session]) -> Iterator[JobHarness]:
    password = secrets.token_urlsafe(24)
    with isolated_db() as db:
        owner_id = uuid4()
        for name, user_id in [("owner", owner_id), ("other", uuid4())]:
            db.add(
                User(
                    id=user_id,
                    email=f"{name}@jobs.example",
                    display_name=name,
                    password_hash=hash_password(password),
                )
            )
            db.flush()
            db.add(UserRole(user_id=user_id, role_name="KNOWLEDGE_MANAGER"))
        document = Document(id=uuid4(), owner_id=owner_id, title="Synthetic job fixture")
        db.add(document)
        db.flush()
        version = DocumentVersion(
            id=uuid4(),
            document_id=document.id,
            version_number=1,
            uploaded_by=owner_id,
            filename="fixture.txt",
            media_type="text/plain",
            size_bytes=1,
            sha256=hashlib.sha256(b"x").hexdigest(),
            object_key=f"test-jobs/{uuid4()}",
            status="UPLOADED",
        )
        db.add(version)
        db.flush()
        job = ensure_job(db, version.id, "text-v1")
        db.commit()

    def session_override() -> Iterator[Session]:
        with isolated_db() as db:
            yield db

    app = create_app(Settings(auth_secret=SecretStr(secrets.token_urlsafe(48))))
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        headers = {}
        for name in ["owner", "other"]:
            response = client.post(
                "/auth/login",
                headers={"X-DocuMind-CSRF": "1"},
                json={"email": f"{name}@jobs.example", "password": password},
            )
            assert response.status_code == 200
            headers[name] = {"Authorization": "Bearer " + response.json()["access_token"]}
        yield JobHarness(isolated_db, client, headers, document.id, version.id, job.id)


def test_enqueue_is_idempotent_authorized_and_has_no_ready_shortcut(jobs: JobHarness) -> None:
    h = jobs
    url = f"/documents/{h.document_id}/versions/{h.version_id}/jobs"
    for _ in range(2):
        response = h.client.post(url, headers=h.headers["owner"])
        assert response.status_code == 202 and response.json()["id"] == str(h.job_id)
    assert (
        h.client.post(url, headers=h.headers["owner"], json={"simulate_ready": True}).status_code
        == 422
    )
    assert h.client.get(url, headers=h.headers["other"]).status_code == 404
    assert h.client.post(url, headers=h.headers["other"]).status_code == 404
    assert h.client.get(url).status_code == 401
    listed = h.client.get(url, headers=h.headers["owner"])
    assert listed.status_code == 200 and listed.json()["total"] == 1
    assert listed.json()["items"][0]["status"] == "PENDING"


def test_duplicate_delivery_does_not_repeat_failed_execution(jobs: JobHarness) -> None:
    sent: list[UUID] = []
    with jobs.factory() as db:
        assert dispatch_pending(db, sent.append)["queued"] == 1
        assert sent == [jobs.job_id]
        # Deliberately missing original: the real pipeline reports a bounded failure.
        assert process_job(db, jobs.job_id) == "FAILED"
        assert process_job(db, jobs.job_id) == "FAILED"
        job = db.get(ProcessingJob, jobs.job_id)
        version = db.get(DocumentVersion, jobs.version_id)
        assert job and job.attempts == 1 and job.error_code == "STORAGE_READ_FAILED"
        assert version and version.status == "FAILED"
        assert dispatch_pending(db, sent.append) == {"queued": 0, "deferred": 0, "failed": 0}


def test_dispatch_backoff_is_bounded_sanitized_and_retry_reuses_job(
    jobs: JobHarness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)

    def unavailable(job_id: UUID) -> None:
        raise OSError("private-password-and-provider-response")

    with jobs.factory() as db:
        job = db.get(ProcessingJob, jobs.job_id)
        assert job
        for attempt in range(1, 6):
            job.next_dispatch_at = utcnow() - timedelta(seconds=1)
            db.commit()
            counts = dispatch_pending(db, unavailable)
            assert counts["failed" if attempt == 5 else "deferred"] == 1
            assert job.dispatch_attempts == attempt and job.attempts == 0
        assert job.status == "DISPATCH_FAILED" and "private-password" not in caplog.text
    url = f"/documents/{jobs.document_id}/jobs/{jobs.job_id}/retry"
    response = jobs.client.post(url, headers=jobs.headers["owner"])
    assert response.status_code == 202 and response.json()["id"] == str(jobs.job_id)
    assert response.json()["dispatch_attempts"] == 0
    assert jobs.client.post(url, headers=jobs.headers["other"]).status_code == 404


def test_execution_attempt_limit_cannot_be_reset_by_api(jobs: JobHarness) -> None:
    with jobs.factory() as db:
        job = db.get(ProcessingJob, jobs.job_id)
        assert job
        job.status, job.attempts, job.error_code = "FAILED", job.max_attempts, "EXTRACTION_FAILED"
        db.commit()
    response = jobs.client.post(
        f"/documents/{jobs.document_id}/jobs/{jobs.job_id}/retry", headers=jobs.headers["owner"]
    )
    assert response.status_code == 409


def test_logical_job_uniqueness_is_enforced_by_postgresql(jobs: JobHarness) -> None:
    with jobs.factory() as db, pytest.raises(IntegrityError), db.begin_nested():
        db.add(ProcessingJob(version_id=jobs.version_id, pipeline_key="text-v1"))
        db.flush()


def test_ready_simulation_exists_only_in_isolated_fixture_data(jobs: JobHarness) -> None:
    with jobs.factory() as db:
        options = db.get_bind().get_execution_options()
        assert str(options["schema_translate_map"][None]).startswith("test_")
        job, version = db.get(ProcessingJob, jobs.job_id), db.get(DocumentVersion, jobs.version_id)
        assert job and version
        job.status, job.stage, job.attempts = "SUCCEEDED", "INDEXED", 1
        version.status = "READY"  # Fixture only; no production flag or endpoint performs this.
        db.commit()
        assert process_job(db, job.id) == "SUCCEEDED"
        assert db.scalar(select(func.count()).select_from(ProcessingJob)) == 1
