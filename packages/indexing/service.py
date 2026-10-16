import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.documents.models import Document, DocumentVersion
from packages.identity.organization import ConflictError, NotFoundError
from packages.parsers.contracts import TextBlock
from packages.parsers.service import ExtractionService
from packages.storage import ObjectStorage

from .chunking import ChunkConfig, EmbeddingProfile, chunk_blocks
from .models import ChunkEmbedding, IndexChunk, IndexRevision


class IndexService:
    def __init__(self, db: Session, storage: ObjectStorage, settings: Settings) -> None:
        self.db, self.storage, self.settings = db, storage, settings

    def prepare(
        self, version_id: UUID, config: ChunkConfig, profile: EmbeddingProfile
    ) -> IndexRevision:
        extraction = ExtractionService(self.db, self.storage, self.settings).extract_version(
            version_id
        )
        blocks = tuple(TextBlock.model_validate(value) for value in extraction.blocks)
        chunks = chunk_blocks(blocks, config)
        payload = {
            "source": extraction.source_sha256,
            "normalized": extraction.normalized_sha256,
            "parser": extraction.parser_revision,
            "chunking": config.model_dump(),
            "embedding": profile.model_dump(),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        version = self.db.scalar(
            select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
        )
        if version is None:
            raise NotFoundError
        existing = self.db.scalar(
            select(IndexRevision).where(
                IndexRevision.version_id == version_id, IndexRevision.fingerprint == fingerprint
            )
        )
        if existing:
            count = self.db.scalar(
                select(func.count())
                .select_from(IndexChunk)
                .where(IndexChunk.index_revision_id == existing.id)
            )
            if count != existing.chunk_count or count != len(chunks):
                raise ConflictError("La revisión no supera la verificación de integridad")
            return existing
        generation = (
            self.db.scalar(
                select(func.max(IndexRevision.generation)).where(
                    IndexRevision.version_id == version_id
                )
            )
            or 0
        ) + 1
        revision_id = uuid5(
            NAMESPACE_URL, f"https://documint.local/index/{version_id}/{fingerprint}"
        )
        revision = IndexRevision(
            id=revision_id,
            version_id=version_id,
            extraction_id=extraction.id,
            generation=generation,
            fingerprint=fingerprint,
            chunk_config=config.model_dump(),
            embedding_profile=profile.model_dump(),
            chunk_count=len(chunks),
        )
        self.db.add(revision)
        self.db.flush()
        self.db.add_all(
            IndexChunk(
                id=uuid5(revision_id, f"{chunk.position}:{chunk.sha256}"),
                index_revision_id=revision_id,
                position=chunk.position,
                text=chunk.text,
                sha256=chunk.sha256,
                spans=[span.model_dump(mode="json") for span in chunk.spans],
            )
            for chunk in chunks
        )
        self.db.commit()
        return revision

    def activate(self, revision_id: UUID) -> bool:
        revision = self.db.get(IndexRevision, revision_id)
        if revision is None:
            raise NotFoundError
        version = self.db.get(DocumentVersion, revision.version_id)
        assert version
        document = self.db.scalar(
            select(Document)
            .where(Document.id == version.document_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert document
        revision = self.db.scalar(
            select(IndexRevision)
            .where(IndexRevision.id == revision_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert revision
        profile = EmbeddingProfile.model_validate(revision.embedding_profile)
        chunks = (
            self.db.scalar(
                select(func.count())
                .select_from(IndexChunk)
                .where(IndexChunk.index_revision_id == revision.id)
            )
            or 0
        )
        indexed = (
            self.db.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .join(IndexChunk)
                .where(
                    IndexChunk.index_revision_id == revision.id,
                    ChunkEmbedding.dimensions == profile.dimensions,
                )
            )
            or 0
        )
        if chunks != revision.chunk_count or chunks == 0 or indexed != chunks:
            raise ConflictError("El índice todavía está incompleto")
        if revision.status != "READY":
            revision.status, revision.indexed_count = "READY", indexed
            self.db.flush()
        active = (
            self.db.get(IndexRevision, document.active_index_revision_id)
            if document.active_index_revision_id
            else None
        )
        activate = True
        if active:
            active_version = self.db.get(DocumentVersion, active.version_id)
            assert active_version
            activate = version.version_number > active_version.version_number or (
                version.id == active_version.id and revision.generation >= active.generation
            )
        if activate:
            document.active_index_revision_id = revision.id
        version.status = "READY"
        self.db.commit()
        return activate
