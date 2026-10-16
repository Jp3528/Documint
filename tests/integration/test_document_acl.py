"""Real PostgreSQL ACL and pagination; storage is an explicit in-memory corpus fixture."""

import hashlib
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_object_storage, get_session
from apps.api.main import create_app
from evals.schema import Manifest, reference_can_read
from packages.config import Settings
from packages.documents.access import document_access
from packages.documents.models import Document, DocumentGrant, DocumentVersion
from packages.identity.models import User
from packages.identity.organization import load_actor
from scripts.seed_demo import PUBLIC_DEMO_PASSWORD, demo_personas, seed_identities

pytestmark = pytest.mark.infrastructure
ROOT = Path(__file__).resolve().parents[2]


def fixture_id(kind: str, name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://documind.example/{kind}/{name}")


class CorpusStorage:
    def __init__(self) -> None:
        self.contents: dict[str, bytes] = {}
        self.reads: list[str] = []

    def put(self, key: str, content: bytes, content_type: str) -> None:
        raise AssertionError("this fixture is for read authorization only")

    def get(self, key: str) -> bytes:
        self.reads.append(key)
        return self.contents[key]

    def delete(self, key: str) -> None:
        raise AssertionError("this fixture must never delete originals")

    def check_ready(self) -> None:
        pass


@dataclass
class CorpusHarness:
    client: TestClient
    factory: sessionmaker[Session]
    storage: CorpusStorage
    manifest: Manifest

    def login(self, persona: str) -> dict[str, str]:
        person = next(p for p in demo_personas().personas if p.id == persona)
        response = self.client.post(
            "/auth/login",
            headers={"X-DocuMind-CSRF": "1"},
            json={"email": person.email, "password": PUBLIC_DEMO_PASSWORD},
        )
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def corpus_library(isolated_db: sessionmaker[Session]) -> Iterator[CorpusHarness]:
    settings = Settings(environment="test", auth_secret=SecretStr(secrets.token_urlsafe(48)))
    manifest = Manifest.model_validate_json((ROOT / "demo_corpus/manifest.json").read_text("utf-8"))
    storage = CorpusStorage()
    with isolated_db() as db:
        seed_identities(db, settings, demo_personas())
        for source in manifest.documents:
            doc_id = fixture_id("documents", source.id)
            content = (ROOT / "demo_corpus/files" / source.file).read_bytes()
            key = f"test-corpus/{doc_id}"
            storage.contents[key] = content
            document = Document(
                id=doc_id,
                owner_id=fixture_id("personas", source.owner),
                department_id=fixture_id("departments", source.department)
                if source.department
                else None,
                title=source.title,
                visibility=source.visibility,
            )
            db.add(document)
            db.flush()
            db.add(
                DocumentVersion(
                    id=fixture_id("versions", source.id),
                    document_id=doc_id,
                    version_number=1,
                    uploaded_by=document.owner_id,
                    filename=source.file,
                    media_type="application/octet-stream",
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    object_key=key,
                    status="UPLOADED",
                )
            )
            for name in source.read_users:
                db.add(
                    DocumentGrant(
                        document_id=doc_id,
                        user_id=fixture_id("personas", name),
                        permission="READ",
                        granted_by=document.owner_id,
                    )
                )
            for role in source.read_roles:
                db.add(
                    DocumentGrant(
                        document_id=doc_id,
                        role_name=role,
                        permission="READ",
                        granted_by=document.owner_id,
                    )
                )
        db.commit()

    def session_override() -> Iterator[Session]:
        with isolated_db() as db:
            yield db

    app = create_app(settings)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_object_storage] = lambda: storage
    with TestClient(app) as client:
        yield CorpusHarness(client, isolated_db, storage, manifest)


def test_sql_acl_matches_all_eighty_persona_document_decisions(
    corpus_library: CorpusHarness,
) -> None:
    h = corpus_library
    with h.factory() as db:
        for person in demo_personas().personas:
            user = db.get(User, fixture_id("personas", person.id))
            assert user
            actual = set(
                db.scalars(select(Document.id).where(document_access(load_actor(db, user))))
            )
            expected = {
                fixture_id("documents", source.id)
                for source in h.manifest.documents
                if reference_can_read(person, source)
            }
            assert actual == expected, person.id


def test_api_pagination_and_each_source_are_authorized_before_storage(
    corpus_library: CorpusHarness,
) -> None:
    h = corpus_library
    for person in demo_personas().personas:
        if not person.active:
            continue
        headers = h.login(person.id)
        expected = {
            str(fixture_id("documents", doc.id))
            for doc in h.manifest.documents
            if reference_can_read(person, doc)
        }
        seen: set[str] = set()
        for offset in range(0, max(len(expected), 1), 2):
            response = h.client.get(f"/documents?limit=2&offset={offset}", headers=headers)
            assert response.status_code == 200 and response.json()["total"] == len(expected)
            seen.update(item["id"] for item in response.json()["items"])
        assert seen == expected
        for source in h.manifest.documents:
            document, version = (
                fixture_id("documents", source.id),
                fixture_id("versions", source.id),
            )
            url = f"/documents/{document}/versions/{version}"
            before = len(h.storage.reads)
            response = h.client.get(url + "/original", headers=headers)
            if str(document) in expected:
                assert response.status_code == 200
                assert response.headers["content-disposition"].startswith("attachment;")
                assert response.headers["x-content-type-options"] == "nosniff"
            else:
                assert response.status_code == 404 and len(h.storage.reads) == before
                assert h.client.get(url, headers=headers).status_code == 404


def test_archive_preserves_authorized_original_and_revoked_grant_hides_it(
    corpus_library: CorpusHarness,
) -> None:
    h = corpus_library
    reader = h.login("auditor_granted")
    admin = h.login("admin")
    document = fixture_id("documents", "incident")
    version = fixture_id("versions", "incident")
    url = f"/documents/{document}"
    assert h.client.patch(url, headers=admin, json={"archived": True}).status_code == 200
    assert h.client.get("/documents", headers=reader).json()["total"] == 0
    assert h.client.get("/documents?include_archived=true", headers=reader).json()["total"] == 1
    assert h.client.get(url + f"/versions/{version}/original", headers=reader).status_code == 200
    grant = h.client.get(url + "/grants", headers=admin).json()["items"][0]
    assert h.client.delete(url + "/grants/" + grant["id"], headers=admin).status_code == 204
    before = len(h.storage.reads)
    assert h.client.get(url + f"/versions/{version}/original", headers=reader).status_code == 404
    assert h.client.get(url, headers=reader).status_code == 404 and len(h.storage.reads) == before


@pytest.mark.parametrize("invalid", ["none", "both", "permission", "duplicate"])
def test_grant_constraints_hold_in_the_database(
    corpus_library: CorpusHarness, invalid: str
) -> None:
    h = corpus_library
    owner = fixture_id("personas", "security_owner")
    payload: dict[str, object] = {
        "document_id": fixture_id("documents", "incident"),
        "permission": "READ",
        "granted_by": owner,
    }
    if invalid == "both":
        payload.update(user_id=owner, role_name="EMPLOYEE")
    elif invalid == "permission":
        payload.update(user_id=owner, permission="ADMIN")
    elif invalid == "duplicate":
        payload["user_id"] = fixture_id("personas", "auditor_granted")
    with h.factory() as db, pytest.raises(IntegrityError), db.begin_nested():
        db.add(DocumentGrant(**payload))
        db.flush()
