import hashlib
import io
import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pypdf import PdfWriter
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_object_storage, get_session
from apps.api.main import create_app
from packages.config import Settings
from packages.documents.models import Document, DocumentVersion
from packages.documents.service import clean_failed_upload, reconcile_upload
from packages.identity.models import User, UserRole
from packages.identity.organization import ConflictError
from packages.identity.security import hash_password
from packages.indexing.chunking import ChunkConfig, EmbeddingProfile
from packages.indexing.models import ChunkEmbedding, IndexChunk, IndexRevision
from packages.indexing.service import IndexService
from packages.parsers.contracts import ParserError
from packages.parsers.models import Extraction
from packages.parsers.service import ExtractionService
from packages.processing.models import ProcessingJob
from packages.providers.fake import FakeEmbeddingProvider
from packages.storage import S3Storage

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.skipif(os.getenv("DOCUMIND_TEST_INFRA") != "1", reason="requires Compose services"),
]
FILES = Path(__file__).resolve().parents[2] / "demo_corpus/files"


class TrackingStorage:
    def __init__(self) -> None:
        self.real = S3Storage(Settings())
        self.keys: list[str] = []
        self.fail_after_put = False

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.keys.append(key)
        self.real.put(key, content, content_type)
        if self.fail_after_put:
            raise EndpointConnectionError(endpoint_url="https://private.invalid")

    def get(self, key: str) -> bytes:
        return self.real.get(key)

    def delete(self, key: str) -> None:
        self.real.delete(key)

    def check_ready(self) -> None:
        self.real.check_ready()


@dataclass
class UploadHarness:
    client: TestClient
    factory: sessionmaker[Session]
    storage: TrackingStorage
    headers: dict[str, dict[str, str]]


@pytest.fixture
def uploads(isolated_db: sessionmaker[Session]) -> Iterator[UploadHarness]:
    password = secrets.token_urlsafe(24)
    users = {
        "owner": "KNOWLEDGE_MANAGER",
        "other": "KNOWLEDGE_MANAGER",
        "employee": "EMPLOYEE",
        "admin": "ADMIN",
    }
    with isolated_db() as db:
        for name, role in users.items():
            user = User(
                email=f"{name}@documind.example",
                display_name=name,
                password_hash=hash_password(password),
            )
            db.add(user)
            db.flush()
            db.add(UserRole(user_id=user.id, role_name=role))
        db.commit()

    def session_override() -> Iterator[Session]:
        with isolated_db() as db:
            yield db

    settings = Settings(
        auth_secret=SecretStr(secrets.token_urlsafe(48)), upload_max_bytes=128 * 1024
    )
    storage = TrackingStorage()
    app = create_app(settings)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        with TestClient(app) as client:
            headers = {}
            for name in users:
                login = client.post(
                    "/auth/login",
                    headers={"X-DocuMind-CSRF": "1"},
                    json={"email": f"{name}@documind.example", "password": password},
                )
                assert login.status_code == 200
                headers[name] = {"Authorization": "Bearer " + login.json()["access_token"]}
            yield UploadHarness(client, isolated_db, storage, headers)
    finally:
        for key in storage.keys:
            storage.real.delete(key)


def test_all_corpus_formats_round_trip_with_real_private_s3(uploads: UploadHarness) -> None:
    h = uploads
    for path in sorted(FILES.iterdir()):
        content = path.read_bytes()
        response = h.client.post(
            "/documents",
            headers=h.headers["owner"],
            files={"file": (path.name, content, "application/x-untrusted")},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["sha256"] == hashlib.sha256(content).hexdigest()
        assert data["size_bytes"] == len(content) and data["status"] == "UPLOADED"
        assert data["visibility"] == "RESTRICTED" and data["version_number"] == 1
        assert "object_key" not in data and response.headers["cache-control"] == "no-store"
        with h.factory() as db:
            version = db.get(DocumentVersion, UUID(data["version_id"]))
            assert version and version.object_key.startswith(
                f"documents/{data['document_id']}/versions/"
            )
            assert (
                path.name not in version.object_key and h.storage.get(version.object_key) == content
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ProcessingJob)
                    .where(ProcessingJob.version_id == version.id)
                )
                == 1
            )


def test_permission_and_invalid_uploads_never_write_objects(uploads: UploadHarness) -> None:
    h = uploads
    assert h.client.post("/documents").status_code == 401
    assert h.client.post("/documents", headers=h.headers["employee"]).status_code == 403
    for name, content, status in [
        ("fake.pdf", b"plaintext", 415),
        ("empty.txt", b"", 422),
        ("large.txt", b"x" * (128 * 1024 + 1), 413),
    ]:
        response = h.client.post(
            "/documents",
            headers=h.headers["owner"],
            files={"file": (name, content, "application/pdf")},
        )
        assert response.status_code == status
    assert h.storage.keys == []
    with h.factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_bounded_multipart_rejects_excess_files_fields_and_chunked_body(
    uploads: UploadHarness,
) -> None:
    h = uploads
    assert (
        h.client.post(
            "/documents",
            headers=h.headers["owner"],
            files=[("file", ("one.txt", b"one")), ("file", ("two.txt", b"two"))],
        ).status_code
        == 400
    )
    assert (
        h.client.post(
            "/documents",
            headers=h.headers["owner"],
            data={"title": "not supported"},
            files={"file": ("one.txt", b"one")},
        ).status_code
        == 400
    )
    boundary = "test-boundary"
    body = (
        (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            'name="file"; filename="large.txt"\r\n\r\n'
        ).encode()
        + b"x" * (220 * 1024)
        + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {**h.headers["owner"], "Content-Type": f"multipart/form-data; boundary={boundary}"}
    response = h.client.post(
        "/documents", headers=headers, content=iter([body[:1000], body[1000:]])
    )
    assert response.status_code == 413 and not h.storage.keys


def test_other_owner_and_mismatched_version_ids_are_indistinguishable(
    uploads: UploadHarness,
) -> None:
    h = uploads
    response = h.client.post(
        "/documents", headers=h.headers["owner"], files={"file": ("private.txt", b"private")}
    )
    assert response.status_code == 201
    data = response.json()
    path = f"/documents/{data['document_id']}/versions/{data['version_id']}"
    assert h.client.get(path, headers=h.headers["owner"]).status_code == 200
    foreign = h.client.get(path, headers=h.headers["other"])
    missing = h.client.get(
        f"/documents/{uuid4()}/versions/{data['version_id']}", headers=h.headers["other"]
    )
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()


def test_timeout_after_real_put_keeps_failed_metadata_and_cleans_object(
    uploads: UploadHarness,
) -> None:
    h = uploads
    h.storage.fail_after_put = True
    response = h.client.post(
        "/documents", headers=h.headers["owner"], files={"file": ("valid.txt", b"valid")}
    )
    assert response.status_code == 503 and "private.invalid" not in response.text
    with h.factory() as db:
        version = db.scalar(select(DocumentVersion))
        assert version and version.status == "UPLOAD_FAILED"
        assert version.error_code == "STORAGE_WRITE_FAILED"
        assert (
            h.storage.real.client.list_objects_v2(
                Bucket=h.storage.real.bucket, Prefix=version.object_key
            ).get("KeyCount")
            == 0
        )


def test_commit_interruption_keeps_recoverable_reservation(
    uploads: UploadHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = uploads
    original = Session.commit
    calls = 0

    def interrupted(db: Session) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("simulated metadata failure")
        original(db)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", interrupted)
        response = h.client.post(
            "/documents", headers=h.headers["owner"], files={"file": ("valid.txt", b"valid")}
        )
    assert response.status_code == 503
    with h.factory() as db:
        version = db.scalar(select(DocumentVersion))
        assert version and version.status == "UPLOADING"
        assert reconcile_upload(db, h.storage, version) == "UPLOADED"


@pytest.mark.parametrize("failure", ["missing", "corrupted", "transient"])
def test_reconcile_distinguishes_absence_integrity_and_temporary_outage(
    uploads: UploadHarness, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    h = uploads
    response = h.client.post(
        "/documents", headers=h.headers["owner"], files={"file": ("valid.txt", b"valid")}
    )
    assert response.status_code == 201
    with h.factory() as db:
        version = db.get(DocumentVersion, UUID(response.json()["version_id"]))
        assert version
        version.status = "UPLOADING"
        db.commit()
        if failure == "missing":
            h.storage.delete(version.object_key)
        elif failure == "corrupted":
            h.storage.put(version.object_key, b"wrong", "text/plain")
        else:

            def unavailable(key: str) -> bytes:
                raise EndpointConnectionError(endpoint_url="https://private.invalid")

            monkeypatch.setattr(h.storage, "get", unavailable)
            with pytest.raises(EndpointConnectionError):
                reconcile_upload(db, h.storage, version)
            assert version.status == "UPLOADING"
            return
        assert reconcile_upload(db, h.storage, version) == "UPLOAD_FAILED"
        expected = "STORAGE_MISSING" if failure == "missing" else "STORAGE_INTEGRITY_FAILED"
        assert version.error_code == expected


def test_unbounded_content_length_header_is_rejected_safely(uploads: UploadHarness) -> None:
    for declared in ["9" * 5000, "-1"]:
        response = uploads.client.post(
            "/documents",
            headers={**uploads.headers["owner"], "Content-Length": declared},
            content=b"",
        )
        assert response.status_code == 413
    assert not uploads.storage.keys


def test_failed_cleanup_keeps_a_reference_and_maintenance_never_deletes_published_objects(
    uploads: UploadHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = uploads
    h.storage.fail_after_put = True

    def unavailable(key: str) -> None:
        raise OSError("simulated cleanup outage")

    with monkeypatch.context() as patch:
        patch.setattr(h.storage, "delete", unavailable)
        response = h.client.post(
            "/documents", headers=h.headers["owner"], files={"file": ("valid.txt", b"valid")}
        )
    assert response.status_code == 503
    with h.factory() as db:
        version = db.scalar(select(DocumentVersion))
        assert version and version.status == "UPLOAD_FAILED"
        assert h.storage.get(version.object_key) == b"valid"
        clean_failed_upload(db, h.storage, version)
        assert version.error_code == "STORAGE_CLEANED"
        version.status = "UPLOADED"
        with pytest.raises(ValueError):
            clean_failed_upload(db, h.storage, version)
        with pytest.raises(ValueError):
            reconcile_upload(db, h.storage, version)


def test_read_and_manage_grants_are_distinct_and_revalidated_without_login(
    uploads: UploadHarness,
) -> None:
    h = uploads
    first = h.client.post(
        "/documents", headers=h.headers["owner"], files={"file": ("v1.txt", b"first original")}
    )
    assert first.status_code == 201
    data = first.json()
    url = f"/documents/{data['document_id']}"
    employee_id = h.client.get("/me", headers=h.headers["employee"]).json()["id"]
    read_grant = {"user_id": employee_id, "permission": "READ"}
    permission = h.client.post(url + "/grants", headers=h.headers["owner"], json=read_grant)
    assert permission.status_code == 201
    assert (
        h.client.post(url + "/grants", headers=h.headers["owner"], json=read_grant).status_code
        == 409
    )
    assert h.client.get(url, headers=h.headers["employee"]).json()["can_manage"] is False
    assert (
        h.client.patch(url, headers=h.headers["employee"], json={"title": "escalation"}).status_code
        == 404
    )
    assert h.client.post(url + "/versions", headers=h.headers["employee"]).status_code == 404
    original = url + f"/versions/{data['version_id']}/original"
    assert h.client.get(original, headers=h.headers["employee"]).content == b"first original"
    assert (
        h.client.delete(
            url + "/grants/" + permission.json()["id"], headers=h.headers["owner"]
        ).status_code
        == 204
    )
    assert h.client.get(original, headers=h.headers["employee"]).status_code == 404
    manage = h.client.post(
        url + "/grants",
        headers=h.headers["owner"],
        json={"role_name": "EMPLOYEE", "permission": "MANAGE"},
    )
    assert manage.status_code == 201
    assert h.client.get(url, headers=h.headers["employee"]).json()["can_manage"] is True
    second = h.client.post(
        url + "/versions",
        headers=h.headers["employee"],
        files={"file": ("v2.txt", b"second original")},
    )
    assert second.status_code == 201 and second.json()["version_number"] == 2
    assert second.json()["version_id"] != data["version_id"]
    assert h.client.get(original, headers=h.headers["owner"]).content == b"first original"
    history = h.client.get(url + "/versions?limit=1&offset=0", headers=h.headers["owner"])
    assert history.status_code == 200 and history.json()["total"] == 2
    assert history.json()["items"][0]["sha256"] == hashlib.sha256(b"second original").hexdigest()


def test_department_visibility_scopes_and_inactive_department_behavior(
    uploads: UploadHarness,
) -> None:
    h = uploads
    admin, owner, employee, other = (
        h.headers[key] for key in ["admin", "owner", "employee", "other"]
    )
    departments = []
    for code in ["ENGINEERING", "FINANCE"]:
        response = h.client.post("/departments", headers=admin, json={"code": code, "name": code})
        assert response.status_code == 201
        departments.append(response.json()["id"])
    for headers in [owner, employee]:
        user = h.client.get("/me", headers=headers).json()["id"]
        assert (
            h.client.post(
                f"/departments/{departments[0]}/memberships", headers=admin, json={"user_id": user}
            ).status_code
            == 201
        )
    created = h.client.post("/documents", headers=owner, files={"file": ("scoped.txt", b"scoped")})
    assert created.status_code == 201
    url = "/documents/" + created.json()["document_id"]
    assert h.client.patch(url, headers=owner, json={"visibility": "DEPARTMENT"}).status_code == 409
    assert (
        h.client.patch(
            url, headers=owner, json={"visibility": "DEPARTMENT", "department_id": departments[1]}
        ).status_code
        == 404
    )
    scoped = h.client.patch(
        url, headers=owner, json={"visibility": "DEPARTMENT", "department_id": departments[0]}
    )
    assert scoped.status_code == 200
    assert h.client.get(url, headers=employee).status_code == 200
    assert h.client.get(url, headers=other).status_code == 404
    assert h.client.patch(url, headers=admin, json={"visibility": "COMPANY"}).status_code == 200
    assert h.client.get(url, headers=other).json()["can_manage"] is False
    assert h.client.patch(url, headers=owner, json={"visibility": "DEPARTMENT"}).status_code == 200
    assert (
        h.client.patch(
            f"/departments/{departments[0]}", headers=admin, json={"active": False}
        ).status_code
        == 200
    )
    assert h.client.get(url, headers=employee).status_code == 404
    assert h.client.get(url, headers=owner).status_code == 200
    assert h.client.patch(url, headers=owner, json={"archived": True}).status_code == 200


def test_database_reservation_failure_never_writes_storage(
    uploads: UploadHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(db: Session) -> None:
        raise SQLAlchemyError("simulated reservation failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", interrupted)
        response = uploads.client.post(
            "/documents", headers=uploads.headers["owner"], files={"file": ("valid.txt", b"valid")}
        )
    assert response.status_code == 503 and not uploads.storage.keys
    with uploads.factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(ProcessingJob)) == 0


@pytest.mark.parametrize(
    "body,status",
    [
        (b"invalid multipart", 400),
        (
            b'--test\r\nContent-Disposition: form-data; name="file"; '
            b'filename="cut.txt"\r\n\r\npartial',
            422,
        ),
    ],
)
def test_malformed_or_truncated_multipart_leaves_no_original_or_job(
    uploads: UploadHarness, body: bytes, status: int
) -> None:
    response = uploads.client.post(
        "/documents",
        headers={**uploads.headers["owner"], "Content-Type": "multipart/form-data; boundary=test"},
        content=body,
    )
    assert response.status_code == status and not uploads.storage.keys
    with uploads.factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(ProcessingJob)) == 0


def test_all_corpus_extractions_persist_once_with_verified_counters_and_locators(
    uploads: UploadHarness,
) -> None:
    h = uploads
    for path in sorted(FILES.iterdir()):
        response = h.client.post(
            "/documents", headers=h.headers["owner"], files={"file": (path.name, path.read_bytes())}
        )
        assert response.status_code == 201
        version_id = UUID(response.json()["version_id"])
        with h.factory() as db:
            service = ExtractionService(db, h.storage, Settings())
            extraction = service.extract_version(version_id)
            assert service.extract_version(version_id).id == extraction.id
            assert extraction.character_count == sum(
                len(block["text"]) for block in extraction.blocks
            )
            assert extraction.block_count == len(extraction.blocks)
            assert all(block["locator"]["format"] == path.suffix[1:] for block in extraction.blocks)
            job = db.scalar(select(ProcessingJob).where(ProcessingJob.version_id == version_id))
            assert job
            assert service.run_stage(job.id) == "WAITING_PIPELINE"
            assert job.stage == "EXTRACTED" and job.attempts == 1
            assert service.run_stage(job.id) == "WAITING_PIPELINE" and job.attempts == 1
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Extraction)
                    .where(Extraction.version_id == version_id)
                )
                == 1
            )
            stored_version = db.get(DocumentVersion, version_id)
            assert stored_version and stored_version.status == "CHUNKING"


@pytest.mark.parametrize("failure", ["empty_pdf", "storage_integrity", "output_limit"])
def test_extraction_errors_persist_failed_without_partial_blocks(
    uploads: UploadHarness, failure: str
) -> None:
    h = uploads
    filename, content = "valid.txt", b"valid text for extraction"
    if failure == "empty_pdf":
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        stream = io.BytesIO()
        writer.write(stream)
        filename, content = "scan.pdf", stream.getvalue()
    response = h.client.post(
        "/documents", headers=h.headers["owner"], files={"file": (filename, content)}
    )
    assert response.status_code == 201
    version_id = UUID(response.json()["version_id"])
    with h.factory() as db:
        version = db.get(DocumentVersion, version_id)
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.version_id == version_id))
        assert version and job
        if failure == "storage_integrity":
            h.storage.put(version.object_key, b"changed", "text/plain")
        settings = Settings(parser_max_characters=4) if failure == "output_limit" else Settings()
        assert ExtractionService(db, h.storage, settings).run_stage(job.id) == "FAILED"
        expected = {
            "empty_pdf": "NO_EXTRACTABLE_TEXT",
            "storage_integrity": "STORAGE_INTEGRITY_FAILED",
            "output_limit": "EXTRACTION_LIMIT",
        }[failure]
        assert job.error_code == expected and version.status == "FAILED" and job.attempts == 1
        assert db.scalar(select(func.count()).select_from(Extraction)) == 0


def test_cached_extraction_is_checked_for_content_integrity(uploads: UploadHarness) -> None:
    h = uploads
    response = h.client.post(
        "/documents", headers=h.headers["owner"], files={"file": ("text.txt", b"original content")}
    )
    assert response.status_code == 201
    with h.factory() as db:
        service = ExtractionService(db, h.storage, Settings())
        version_id = UUID(response.json()["version_id"])
        extraction = service.extract_version(version_id)
        extraction.blocks = [
            {**extraction.blocks[0], "text": "X" * len(extraction.blocks[0]["text"])}
        ]
        db.commit()
        with pytest.raises(ParserError, match="EXTRACTION_INTEGRITY_FAILED"):
            service.extract_version(version_id)


def test_revision_activation_requires_complete_vectors_and_preserves_old_evidence(
    uploads: UploadHarness,
) -> None:
    h = uploads
    content = b"Knowledge needs verifiable evidence. " * 20
    created = h.client.post(
        "/documents", headers=h.headers["owner"], files={"file": ("index.txt", content)}
    )
    assert created.status_code == 201
    version_id = UUID(created.json()["version_id"])
    provider = FakeEmbeddingProvider()
    profile = EmbeddingProfile(
        name=provider.model.name, revision=provider.model.revision, mode="FAKE", dimensions=16
    )
    with h.factory() as db:
        service = IndexService(db, h.storage, Settings())
        first = service.prepare(
            version_id, ChunkConfig(max_characters=64, overlap_characters=8), profile
        )
        assert (
            service.prepare(
                version_id, ChunkConfig(max_characters=64, overlap_characters=8), profile
            ).id
            == first.id
        )
        chunks = list(
            db.scalars(
                select(IndexChunk)
                .where(IndexChunk.index_revision_id == first.id)
                .order_by(IndexChunk.position)
            )
        )
        evidence = [(chunk.id, chunk.text, chunk.sha256, chunk.spans) for chunk in chunks]
        with pytest.raises(ConflictError):
            service.activate(first.id)
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(
                update(IndexRevision)
                .where(IndexRevision.id == first.id)
                .values(status="READY", indexed_count=first.chunk_count)
            )
        vectors = provider.embed([chunk.text for chunk in chunks]).vectors
        db.add_all(
            ChunkEmbedding(chunk_id=chunk.id, dimensions=16, embedding=list(vector))
            for chunk, vector in zip(chunks, vectors, strict=True)
        )
        db.commit()
        assert service.activate(first.id)
        for operation in [
            update(IndexChunk).where(IndexChunk.id == chunks[0].id).values(text="forged"),
            delete(IndexChunk).where(IndexChunk.id == chunks[0].id),
        ]:
            with pytest.raises(IntegrityError), db.begin_nested():
                db.execute(operation)
        newer = service.prepare(
            version_id, ChunkConfig(max_characters=96, overlap_characters=12), profile
        )
        document = db.get(Document, UUID(created.json()["document_id"]))
        assert document and document.active_index_revision_id == first.id
        newer_chunks = list(
            db.scalars(
                select(IndexChunk)
                .where(IndexChunk.index_revision_id == newer.id)
                .order_by(IndexChunk.position)
            )
        )
        vectors = provider.embed([chunk.text for chunk in newer_chunks]).vectors
        db.add_all(
            ChunkEmbedding(chunk_id=chunk.id, dimensions=16, embedding=list(vector))
            for chunk, vector in zip(newer_chunks, vectors, strict=True)
        )
        db.commit()
        assert service.activate(newer.id)
        assert not service.activate(first.id)
        assert document.active_index_revision_id == newer.id
        old = list(
            db.scalars(
                select(IndexChunk)
                .where(IndexChunk.index_revision_id == first.id)
                .order_by(IndexChunk.position)
            )
        )
        assert [(chunk.id, chunk.text, chunk.sha256, chunk.spans) for chunk in old] == evidence
        other = Document(owner_id=document.owner_id, title="Other document fixture")
        db.add(other)
        db.commit()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(
                update(Document)
                .where(Document.id == other.id)
                .values(active_index_revision_id=first.id)
            )


@pytest.mark.parametrize(
    "vector,dimensions",
    [
        ([0.0] * 16, 16),
        ([1.0] * 16, 15),
        ([1.0] * 32, 32),
    ],
)
def test_invalid_vectors_cannot_enter_the_physical_index(
    uploads: UploadHarness, vector: list[float], dimensions: int
) -> None:
    h = uploads
    created = h.client.post(
        "/documents",
        headers=h.headers["owner"],
        files={"file": ("index.txt", b"verifiable knowledge")},
    )
    assert created.status_code == 201
    with h.factory() as db:
        revision = IndexService(db, h.storage, Settings()).prepare(
            UUID(created.json()["version_id"]),
            ChunkConfig(),
            EmbeddingProfile(name="fake-sha256", revision="1", mode="FAKE", dimensions=16),
        )
        chunk = db.scalar(select(IndexChunk).where(IndexChunk.index_revision_id == revision.id))
        assert chunk
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(ChunkEmbedding(chunk_id=chunk.id, dimensions=dimensions, embedding=vector))
            db.flush()
