import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from packages.config import Settings
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.security import utcnow
from packages.indexing.models import ChunkEmbedding, EmbeddingCall, IndexChunk, IndexRevision
from packages.processing.enqueue import ensure_job
from packages.processing.models import ProcessingJob
from packages.processing.service import dispatch_pending, process_job, retry_job
from packages.providers.contracts import EmbeddingBatch, ProviderError
from packages.providers.fake import FakeEmbeddingProvider
from packages.storage import S3Storage

pytestmark = pytest.mark.infrastructure


@dataclass
class PipelineHarness:
    factory: sessionmaker[Session]
    storage: S3Storage
    settings: Settings
    job_id: UUID
    version_id: UUID
    document_id: UUID


@pytest.fixture
def pipeline(concurrent_db: sessionmaker[Session]) -> Iterator[PipelineHarness]:
    settings = Settings(
        embedding_provider="fake", chunk_max_characters=64, chunk_overlap_characters=8
    )
    storage = S3Storage(settings)
    content = b"Verified statements retain their original evidence. " * 100
    key = f"test-pipeline/{uuid4()}"
    storage.put(key, content, "text/plain")
    try:
        with concurrent_db() as db:
            user = User(
                email="pipeline@synthetic.example",
                display_name="Pipeline fixture",
                password_hash="!no-login-fixture",
            )
            db.add(user)
            db.flush()
            document = Document(owner_id=user.id, title="Synthetic pipeline fixture")
            db.add(document)
            db.flush()
            version = DocumentVersion(
                document_id=document.id,
                version_number=1,
                uploaded_by=user.id,
                filename="fixture.txt",
                media_type="text/plain",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                object_key=key,
                status="UPLOADED",
            )
            db.add(version)
            db.flush()
            job = ensure_job(db, version.id, "text-v1")
            db.commit()
            yield PipelineHarness(concurrent_db, storage, settings, job.id, version.id, document.id)
    finally:
        storage.delete(key)


def test_full_pipeline_persists_real_vectors_and_duplicate_delivery_is_noop(
    pipeline: PipelineHarness,
) -> None:
    h = pipeline
    provider = FakeEmbeddingProvider()
    with h.factory() as db, patch.object(provider, "embed", wraps=provider.embed) as embed:
        assert process_job(db, h.job_id, settings=h.settings, provider=provider) == "SUCCEEDED"
        calls = embed.call_count
        assert calls > 1
        assert process_job(db, h.job_id, settings=h.settings, provider=provider) == "SUCCEEDED"
        assert embed.call_count == calls
        job = db.get(ProcessingJob, h.job_id)
        version = db.get(DocumentVersion, h.version_id)
        document = db.get(Document, h.document_id)
        assert job and version and document and job.attempts == 1
        revision = db.get(IndexRevision, job.index_revision_id)
        assert revision and revision.status == version.status == "READY"
        assert document.active_index_revision_id == revision.id
        assert (
            revision.chunk_count
            == revision.indexed_count
            == db.scalar(select(func.count()).select_from(ChunkEmbedding))
        )
        assert revision.embedding_profile["mode"] == "FAKE"
        assert db.scalar(select(func.count()).select_from(EmbeddingCall)) == calls


def test_retry_resumes_only_missing_vectors(pipeline: PipelineHarness) -> None:
    h = pipeline

    class InterruptedProvider(FakeEmbeddingProvider):
        calls = 0

        def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
            self.calls += 1
            if self.calls == 2:
                raise ProviderError("EMBEDDING_REQUEST_FAILED")
            return super().embed(texts)

    with h.factory() as db:
        assert (
            process_job(db, h.job_id, settings=h.settings, provider=InterruptedProvider())
            == "FAILED"
        )
        assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 32
        document = db.get(Document, h.document_id)
        assert document and document.active_index_revision_id is None
        job = db.get(ProcessingJob, h.job_id)
        assert job and job.attempts == 1
        retry_job(db, job)
        provider = FakeEmbeddingProvider()
        with patch.object(provider, "embed", wraps=provider.embed) as embed:
            assert process_job(db, h.job_id, settings=h.settings, provider=provider) == "SUCCEEDED"
            assert len(embed.call_args_list[0].args[0]) <= 32
        assert job.attempts == 2
        assert db.scalar(select(func.count()).select_from(IndexRevision)) == 1
        assert db.scalar(select(func.sum(EmbeddingCall.chunk_count))) == db.scalar(
            select(func.count()).select_from(IndexChunk)
        )


def test_activation_and_successful_job_commit_together(
    pipeline: PipelineHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = pipeline
    with h.factory() as db:
        original_commit = db.commit

        def fail_final_commit() -> None:
            job = db.get(ProcessingJob, h.job_id)
            if job and job.status == "SUCCEEDED":
                raise SQLAlchemyError("synthetic transaction interruption")
            original_commit()

        with monkeypatch.context() as local:
            local.setattr(db, "commit", fail_final_commit)
            assert process_job(db, h.job_id, settings=h.settings) == "FAILED"
        document, version = db.get(Document, h.document_id), db.get(DocumentVersion, h.version_id)
        assert document and document.active_index_revision_id is None
        assert version and version.status == "FAILED"
        assert not list(db.scalars(select(IndexRevision).where(IndexRevision.status == "READY")))
        job = db.get(ProcessingJob, h.job_id)
        assert job
        retry_job(db, job)
        assert process_job(db, h.job_id, settings=h.settings) == "SUCCEEDED"


def test_live_duplicate_is_skipped_and_replaced_worker_cannot_publish(
    pipeline: PipelineHarness,
) -> None:
    h = pipeline

    class ReplacedProvider(FakeEmbeddingProvider):
        def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
            with h.factory() as other:
                assert process_job(other, h.job_id, settings=h.settings) == "RUNNING"
                job = other.get(ProcessingJob, h.job_id)
                assert job
                job.run_token, job.lease_expires_at = uuid4(), utcnow() - timedelta(seconds=1)
                other.commit()
            return super().embed(texts)

    with h.factory() as db:
        assert (
            process_job(db, h.job_id, settings=h.settings, provider=ReplacedProvider())
            == "LEASE_LOST"
        )
        assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0
        assert dispatch_pending(db, lambda _: None, only_job_ids=(h.job_id,))["queued"] == 1
        assert process_job(db, h.job_id, settings=h.settings) == "SUCCEEDED"
        job = db.get(ProcessingJob, h.job_id)
        assert job and job.attempts == 2


def test_failed_reindex_preserves_active_index_and_ready_version(pipeline: PipelineHarness) -> None:
    h = pipeline

    class UnavailableProvider(FakeEmbeddingProvider):
        def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
            raise ProviderError("EMBEDDING_REQUEST_FAILED")

    with h.factory() as db:
        assert process_job(db, h.job_id, settings=h.settings) == "SUCCEEDED"
        document = db.get(Document, h.document_id)
        assert document
        old_revision = document.active_index_revision_id
        job = ensure_job(db, h.version_id, "text-v2")
        db.commit()
        changed = h.settings.model_copy(update={"chunk_max_characters": 96})
        assert process_job(db, job.id, settings=changed, provider=UnavailableProvider()) == "FAILED"
        assert document.active_index_revision_id == old_revision
        version = db.get(DocumentVersion, h.version_id)
        assert version and version.status == "READY"
        retained = db.get(IndexRevision, old_revision)
        assert retained and retained.status == "READY"


def test_embedding_configuration_cannot_change_after_chunks_are_prepared(
    pipeline: PipelineHarness,
) -> None:
    h = pipeline

    class UnavailableProvider(FakeEmbeddingProvider):
        def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
            raise ProviderError("EMBEDDING_REQUEST_FAILED")

    with h.factory() as db:
        assert (
            process_job(db, h.job_id, settings=h.settings, provider=UnavailableProvider())
            == "FAILED"
        )
        revision = db.scalar(select(IndexRevision))
        assert revision and revision.indexed_count == 0
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(
                update(IndexRevision)
                .where(IndexRevision.id == revision.id)
                .values(embedding_profile=revision.embedding_profile | {"name": "different-model"})
            )
