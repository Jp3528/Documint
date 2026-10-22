from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_session
from apps.api.main import create_app
from evals.schema import reference_can_read
from packages.config import Settings
from packages.documents.models import Document, DocumentGrant, DocumentVersion
from packages.documents.service import DocumentService
from packages.documents.validation import validate_upload
from packages.identity.models import DepartmentMember, User, UserRole
from packages.identity.organization import NotFoundError, load_actor
from packages.indexing.chunking import ChunkConfig
from packages.indexing.service import IndexService
from packages.processing.enqueue import ensure_job
from packages.processing.service import process_job
from packages.providers.contracts import EmbeddingBatch, ProviderError
from packages.providers.fake import FakeEmbeddingProvider
from packages.providers.validation import embedding_profile
from packages.retrieval.citations import CitationService
from packages.retrieval.contracts import SearchRequest
from packages.retrieval.fusion import FusionConfig
from packages.retrieval.service import RetrievalService
from packages.storage import S3Storage
from scripts.seed_corpus import corpus_document_id, demo_manifest, identity_id, seed_corpus
from scripts.seed_demo import PUBLIC_DEMO_PASSWORD, demo_personas

pytestmark = pytest.mark.infrastructure


@dataclass
class SearchHarness:
    factory: sessionmaker[Session]
    settings: Settings
    storage: S3Storage
    versions: dict[str, UUID]


@pytest.fixture
def indexed(isolated_db: sessionmaker[Session]) -> Iterator[SearchHarness]:
    settings = Settings(
        embedding_provider="fake", auth_secret=SecretStr("test-search-signing-key" * 3)
    )
    storage, keys = S3Storage(settings), []
    try:
        with isolated_db() as db:
            versions = seed_corpus(db, storage, settings, demo_manifest())
            keys = list(db.scalars(select(DocumentVersion.object_key)))
            for version in versions.values():
                job = ensure_job(db, version, settings.processing_pipeline_key)
                db.commit()
                assert process_job(db, job.id, settings=settings) == "SUCCEEDED"
        yield SearchHarness(isolated_db, settings, storage, versions)
    finally:
        with isolated_db() as db:
            keys = list(db.scalars(select(DocumentVersion.object_key))) or keys
        for key in keys:
            storage.delete(key)


def service(db: Session, persona: str) -> RetrievalService:
    user = db.get(User, identity_id("personas", persona))
    assert user
    return RetrievalService(db, load_actor(db, user))


def test_lexical_and_vector_only_return_authorized_active_chunks(indexed: SearchHarness) -> None:
    h = indexed
    for person in demo_personas().personas:
        allowed = {
            corpus_document_id(doc.id)
            for doc in demo_manifest().documents
            if reference_can_read(person, doc)
        }
        with h.factory() as db:
            retrieval = service(db, person.id)
            request = SearchRequest(
                query="Lumen OR Atlas OR viajes OR datos OR presupuesto", limit=50
            )
            lexical = retrieval.lexical(request)
            provider = FakeEmbeddingProvider()
            with patch.object(provider, "embed", wraps=provider.embed) as embed:
                vector = retrieval.vector(request, provider)
                if not allowed:
                    embed.assert_not_called()
            assert {row.document_id for row in lexical.candidates} <= allowed
            assert {row.document_id for row in vector.candidates} == allowed
            assert vector.embedding_mode == "FAKE"
            assert lexical == retrieval.lexical(request)
            for result in (lexical, vector):
                assert [row.rank for row in result.candidates] == list(
                    range(1, len(result.candidates) + 1)
                )
                for candidate in result.candidates:
                    document = db.get(Document, candidate.document_id)
                    assert (
                        document
                        and document.active_index_revision_id == candidate.index_revision_id
                    )


def test_metadata_filters_archiving_and_acl_revocation_are_applied_in_sql(
    indexed: SearchHarness,
) -> None:
    h = indexed
    with h.factory() as db:
        retrieval = service(db, "engineer")
        request = SearchRequest(query="datos", document_id=corpus_document_id("runbook"))
        assert retrieval.lexical(request).candidates
        assert retrieval.vector(request, FakeEmbeddingProvider()).candidates
        restricted = SearchRequest(query="420000", document_id=corpus_document_id("finance"))
        assert not retrieval.lexical(restricted).candidates
        with patch.object(FakeEmbeddingProvider, "embed") as embed:
            assert not retrieval.vector(restricted, FakeEmbeddingProvider()).candidates
            embed.assert_not_called()
        pdfs = SearchRequest(query="Lumen", file_type="pdf", limit=50)
        assert all(
            c.filename.endswith(".pdf")
            for c in retrieval.vector(pdfs, FakeEmbeddingProvider()).candidates
        )
        people = SearchRequest(
            query="Lumen", department_id=identity_id("departments", "people"), limit=50
        )
        assert {
            c.document_id for c in retrieval.vector(people, FakeEmbeddingProvider()).candidates
        } == {corpus_document_id("travel"), corpus_document_id("onboarding")}
        document = db.get(Document, corpus_document_id("runbook"))
        assert document
        document.archived = True
        db.commit()
        assert not retrieval.lexical(request).candidates
        assert not retrieval.vector(request, FakeEmbeddingProvider()).candidates
        auditor = service(db, "auditor_granted")
        incident = SearchRequest(query="Atlas")
        assert auditor.lexical(incident).candidates
        grant = db.scalar(
            select(DocumentGrant).where(DocumentGrant.document_id == corpus_document_id("incident"))
        )
        assert grant
        db.delete(grant)
        db.commit()
        assert not auditor.lexical(incident).candidates
        assert not auditor.vector(incident, FakeEmbeddingProvider()).candidates


def test_top_k_follows_acl_and_vector_profiles_are_never_mixed(indexed: SearchHarness) -> None:
    h = indexed
    with h.factory() as db:
        admin = service(db, "admin").actor
        uploads = DocumentService(db, admin, h.storage)
        for restricted, content in [
            (True, b"galaxia " * 100),
            (False, b"galaxia visible"),
        ]:
            document, version = uploads.create(validate_upload("rank.txt", content, h.settings))
            document.visibility = "RESTRICTED" if restricted else "COMPANY"
            db.commit()
            job = ensure_job(db, version.id, "text-v1")
            db.commit()
            assert process_job(db, job.id, settings=h.settings) == "SUCCEEDED"
            if not restricted:
                visible_id, visible_version = document.id, version.id
        retrieval = service(db, "engineer")
        request = SearchRequest(query="galaxia", limit=1)
        assert retrieval.lexical(request).candidates[0].document_id == visible_id
        index, provider = IndexService(db, h.storage, h.settings), FakeEmbeddingProvider(32)
        revision = index.prepare(visible_version, ChunkConfig(), embedding_profile(provider.model))
        index.embed(revision.id, provider)
        index.activate(revision.id)
        old = retrieval.vector(
            SearchRequest(query="galaxia", document_id=visible_id), FakeEmbeddingProvider()
        )
        assert not old.candidates
        current = retrieval.vector(SearchRequest(query="galaxia", document_id=visible_id), provider)
        assert current.candidates and current.candidates[0].index_revision_id == revision.id


def test_search_api_validation_authentication_and_safe_provider_errors(
    indexed: SearchHarness,
) -> None:
    h = indexed

    def override() -> Iterator[Session]:
        with h.factory() as db:
            yield db

    app = create_app(h.settings)
    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        assert client.post("/search", json={"query": "viajes"}).status_code == 401
        login = client.post(
            "/auth/login",
            headers={"X-DocuMind-CSRF": "1"},
            json={"email": "ingenieria@documind.example", "password": PUBLIC_DEMO_PASSWORD},
        )
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        for body in [
            {"query": " "},
            {"query": "x", "limit": 51},
            {"query": "x", "file_type": "exe"},
            {"query": "x", "embedding": [0, 1]},
            {"query": "x" * 1001},
        ]:
            assert client.post("/search", json=body, headers=headers).status_code == 422
        result = client.post("/search", json={"query": "viajes"}, headers=headers)
        assert result.status_code == 200 and result.json()["candidates"]
        assert result.headers["Cache-Control"] == "no-store"
        assert "object_key" not in result.text and "embedding" not in result.json()["candidates"][0]
        hit = result.json()["candidates"][0]
        opened = client.get(hit["source_url"], headers=headers)
        assert opened.status_code == 200 and opened.headers["Cache-Control"] == "no-store"
        assert opened.json()["sha256"] == hit["sha256"] and opened.json()["text"]
        assert "text" not in hit and "object_key" not in opened.text
        missing = client.get("/sources/00000000-0000-0000-0000-000000000000", headers=headers)
        with h.factory() as db:
            denied_id = (
                service(db, "finance").lexical(SearchRequest(query="420000")).candidates[0].chunk_id
            )
        denied = client.get(f"/sources/{denied_id}", headers=headers)
        assert missing.status_code == denied.status_code == 404 and missing.json() == denied.json()
        injection = client.post(
            "/search", json={"query": "'); DROP TABLE users; --"}, headers=headers
        )
        assert injection.status_code == 200
        with patch(
            "apps.api.search.make_embedding_provider", side_effect=ProviderError("private-key")
        ):
            error = client.post(
                "/search", json={"query": "viajes", "method": "vector"}, headers=headers
            )
            assert error.status_code == 503 and "private-key" not in error.text


@pytest.mark.parametrize("revocation", ["grant", "membership", "status", "role"])
def test_acl_revocation_during_query_embedding_excludes_evidence(
    indexed: SearchHarness,
    revocation: str,
) -> None:
    h = indexed
    with h.factory() as db:
        retrieval = service(db, "auditor_granted" if revocation == "grant" else "engineer")

        class RevokingProvider(FakeEmbeddingProvider):
            def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
                if revocation == "grant":
                    grant = db.scalar(
                        select(DocumentGrant).where(
                            DocumentGrant.document_id == corpus_document_id("incident")
                        )
                    )
                    assert grant
                    db.delete(grant)
                elif revocation == "membership":
                    membership = db.scalar(
                        select(DepartmentMember).where(
                            DepartmentMember.user_id == retrieval.actor.id
                        )
                    )
                    assert membership
                    db.delete(membership)
                elif revocation == "role":
                    role = db.scalar(select(UserRole).where(UserRole.user_id == retrieval.actor.id))
                    assert role
                    db.delete(role)
                else:
                    user = db.get(User, retrieval.actor.id)
                    assert user
                    user.status = "INACTIVE"
                db.commit()
                return super().embed(texts)

        request = SearchRequest(
            query="Atlas" if revocation == "grant" else "datos",
            document_id=corpus_document_id("incident" if revocation == "grant" else "runbook"),
        )
        assert not retrieval.hybrid(request, RevokingProvider()).candidates


def test_hybrid_is_deduplicated_diverse_and_configuration_is_visible(
    indexed: SearchHarness,
) -> None:
    h = indexed
    with h.factory() as db:
        retrieval = service(db, "engineer")
        request = SearchRequest(query="viajes", method="hybrid", limit=10)
        result = retrieval.hybrid(
            request, FakeEmbeddingProvider(), FusionConfig(max_per_document=1)
        )
        assert result.method == "hybrid" and result.embedding_mode == "FAKE"
        assert result.configuration and result.configuration["max_per_document"] == 1
        assert len({c.document_id for c in result.candidates}) == len(result.candidates)
        assert len({c.chunk_id for c in result.candidates}) == len(result.candidates)
        assert result == retrieval.hybrid(
            request, FakeEmbeddingProvider(), FusionConfig(max_per_document=1)
        )
        with patch.object(FakeEmbeddingProvider, "embed") as embed:
            lexical_only = retrieval.hybrid(
                request, FakeEmbeddingProvider(), FusionConfig(vector_weight=0)
            )
            embed.assert_not_called()
            assert lexical_only.candidates and lexical_only.embedding_mode is None


def test_citations_reconstruct_real_locators_and_preserve_historical_sources(
    indexed: SearchHarness,
) -> None:
    h = indexed
    with h.factory() as db:
        retrieval = service(db, "admin")
        result = retrieval.lexical(
            SearchRequest(query="viajes", document_id=corpus_document_id("travel"))
        )
        citation = CitationService(db, retrieval.actor)
        view = citation.search_view(result)
        assert view.candidates
        hit = view.candidates[0]
        original = citation.source(hit.chunk_id)
        assert hit.sha256 == original.sha256 and len(hit.snippet) <= 500
        assert hit.locators[0].page == 1 and original.text.startswith(hit.snippet.rstrip("…"))
        assert hit.source_url == f"/sources/{hit.chunk_id}"
        assert str(hit.version_id) in hit.original_url
        index = IndexService(db, h.storage, h.settings)
        newer = index.prepare(
            hit.version_id,
            ChunkConfig(max_characters=128, overlap_characters=16),
            embedding_profile(FakeEmbeddingProvider().model),
        )
        index.embed(newer.id, FakeEmbeddingProvider())
        index.activate(newer.id)
        assert citation.source(hit.chunk_id) == original
        document = db.get(Document, hit.document_id)
        assert document
        document.archived = True
        db.commit()
        assert not retrieval.lexical(
            SearchRequest(query="viajes", document_id=hit.document_id)
        ).candidates
        assert citation.source(hit.chunk_id) == original
        auditor = service(db, "auditor_granted")
        candidate = auditor.lexical(SearchRequest(query="Atlas")).candidates[0]
        restricted = CitationService(db, auditor.actor)
        assert restricted.source(candidate.chunk_id)
        grant = db.scalar(
            select(DocumentGrant).where(DocumentGrant.document_id == corpus_document_id("incident"))
        )
        assert grant
        db.delete(grant)
        db.commit()
        with pytest.raises(NotFoundError):
            restricted.source(candidate.chunk_id)
