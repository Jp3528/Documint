import hashlib
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
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_object_storage, get_session
from apps.api.main import create_app
from packages.config import Settings
from packages.documents.models import Document, DocumentVersion
from packages.documents.service import clean_failed_upload, reconcile_upload
from packages.identity.models import User, UserRole
from packages.identity.security import hash_password
from packages.processing.models import ProcessingJob
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
