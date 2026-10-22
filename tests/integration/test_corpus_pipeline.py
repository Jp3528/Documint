import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from evals.schema import GoldenDataset, Manifest, reference_can_read
from packages.config import Settings
from packages.documents.access import document_access
from packages.documents.models import Document, DocumentVersion
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.indexing.chunking import ChunkConfig, ChunkSpan, chunk_blocks
from packages.indexing.models import ChunkEmbedding, IndexChunk, IndexRevision
from packages.parsers.contracts import TextBlock
from packages.parsers.models import Extraction
from packages.processing.enqueue import ensure_job
from packages.processing.models import ProcessingJob
from packages.processing.service import process_job
from packages.providers.fake import FakeEmbeddingProvider
from packages.storage import S3Storage
from scripts.seed_corpus import (
    ROOT,
    corpus_document_id,
    demo_manifest,
    identity_id,
    seed_corpus,
)
from scripts.seed_demo import demo_personas

pytestmark = pytest.mark.infrastructure


def test_all_eight_originals_ready_repeatable_authorized_and_reindexable(
    isolated_db: sessionmaker[Session],
) -> None:
    settings = Settings(
        embedding_provider="fake", chunk_max_characters=128, chunk_overlap_characters=16
    )
    storage, manifest = S3Storage(settings), demo_manifest()
    keys: list[str] = []
    try:
        with isolated_db() as db:
            versions = seed_corpus(db, storage, settings, manifest)
            keys = list(db.scalars(select(DocumentVersion.object_key)))
            assert len(versions) == 8
            originals, evidence = {}, {}
            for item in manifest.documents:
                version = db.get(DocumentVersion, versions[item.id])
                assert version
                originals[item.id] = (version.id, version.sha256, version.object_key)
                assert hashlib.sha256(storage.get(version.object_key)).hexdigest() == item.sha256
                job = ensure_job(db, version.id, settings.processing_pipeline_key)
                db.commit()
                assert process_job(db, job.id, settings=settings) == "SUCCEEDED"
                assert version.status == "READY" and job.attempts == 1
                revision = db.get(IndexRevision, job.index_revision_id)
                assert revision and revision.chunk_count == revision.indexed_count > 0
                extraction = db.get(Extraction, revision.extraction_id)
                assert extraction and extraction.source_sha256 == item.sha256
                blocks = tuple(TextBlock.model_validate(value) for value in extraction.blocks)
                expected = chunk_blocks(
                    blocks, ChunkConfig(max_characters=128, overlap_characters=16)
                )
                chunks = list(
                    db.scalars(
                        select(IndexChunk)
                        .where(IndexChunk.index_revision_id == revision.id)
                        .order_by(IndexChunk.position)
                    )
                )
                assert [(c.text, c.sha256, c.spans) for c in chunks] == [
                    (c.text, c.sha256, [s.model_dump(mode="json") for s in c.spans])
                    for c in expected
                ]
                evidence[item.id] = [(c.id, c.text, c.sha256, c.spans) for c in chunks]
                for chunk in chunks:
                    vector = db.get(ChunkEmbedding, chunk.id)
                    assert vector and vector.dimensions == 16
                    assert list(vector.embedding) == pytest.approx(
                        FakeEmbeddingProvider().embed([chunk.text]).vectors[0], abs=1e-6
                    )
                    for value in chunk.spans:
                        span = ChunkSpan.model_validate(value)
                        assert span.locator == blocks[span.block_index].locator
                        assert (
                            blocks[span.block_index].text[span.char_start : span.char_end]
                            in chunk.text
                        )

            assert seed_corpus(db, storage, settings, manifest) == versions
            assert db.scalar(select(func.count()).select_from(Document)) == 8
            assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 8
            assert db.scalar(select(func.count()).select_from(Extraction)) == 8
            assert db.scalar(select(func.count()).select_from(IndexRevision)) == 8
            jobs = list(db.scalars(select(ProcessingJob)))
            assert len(jobs) == 8
            for job in jobs:
                assert (
                    process_job(db, job.id, settings=settings) == "SUCCEEDED" and job.attempts == 1
                )
            for person in demo_personas().personas:
                user = db.get(User, identity_id("personas", person.id))
                assert user
                actual = set(
                    db.scalars(select(Document.id).where(document_access(load_actor(db, user))))
                )
                assert actual == {
                    corpus_document_id(item.id)
                    for item in manifest.documents
                    if reference_can_read(person, item)
                }
            golden = GoldenDataset.model_validate_json(
                (ROOT / "evals/golden.json").read_text("utf-8")
            )
            for case in golden.cases:
                for reference in case.evidence:
                    snapshot = db.scalar(
                        select(Extraction).where(
                            Extraction.version_id == versions[reference.document_id]
                        )
                    )
                    assert snapshot and reference.quote in "\n".join(
                        b["text"] for b in snapshot.blocks
                    )

            changed = settings.model_copy(update={"chunk_max_characters": 112})
            job = ensure_job(db, versions["deploy"], "text-review-v2")
            db.commit()
            assert process_job(db, job.id, settings=changed) == "SUCCEEDED"
            document = db.get(Document, corpus_document_id("deploy"))
            assert document and document.active_index_revision_id == job.index_revision_id
            for item in manifest.documents:
                old = evidence[item.id]
                stored = list(
                    db.scalars(
                        select(IndexChunk)
                        .where(IndexChunk.id.in_([row[0] for row in old]))
                        .order_by(IndexChunk.position)
                    )
                )
                assert [(c.id, c.text, c.sha256, c.spans) for c in stored] == old
                version = db.get(DocumentVersion, versions[item.id])
                assert (
                    version
                    and (version.id, version.sha256, version.object_key) == originals[item.id]
                )
            document.title = "Edited by the demo operator"
            db.commit()
            with pytest.raises(ValueError, match="fixture conflict"):
                seed_corpus(db, storage, settings, manifest)
            assert document.title == "Edited by the demo operator"
    finally:
        for key in keys:
            storage.delete(key)


def test_corrupt_corpus_is_rejected_before_creating_identities_or_documents(
    isolated_db: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings, original = Settings(), demo_manifest()
    item = next(item for item in original.documents if item.id == "finance")
    manifest = Manifest(version=original.version, synthetic=True, documents=[item])
    (tmp_path / item.file).write_bytes(b"Altered synthetic original")
    with isolated_db() as db:
        with pytest.raises(ValueError, match="integrity check"):
            seed_corpus(db, S3Storage(settings), settings, manifest, tmp_path)
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 0
        with pytest.raises(ValueError, match="forbidden in production"):
            seed_corpus(db, S3Storage(settings), Settings(environment="production"), original)
