from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from packages.database import Base
from packages.documents.models import Document

from .invariants import install_invariant


class IndexRevision(Base):
    __tablename__ = "index_revisions"
    __table_args__ = (
        UniqueConstraint("version_id", "fingerprint", name="uq_index_revision_fingerprint"),
        UniqueConstraint("version_id", "generation", name="uq_index_revision_generation"),
        CheckConstraint(
            "generation > 0 AND chunk_count > 0 AND indexed_count BETWEEN 0 AND chunk_count",
            name="counts_valid",
        ),
        CheckConstraint("status IN ('CHUNKED','INDEXING','READY','FAILED')", name="status_valid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("document_versions.id"), index=True)
    extraction_id: Mapped[UUID] = mapped_column(ForeignKey("extractions.id"))
    generation: Mapped[int] = mapped_column()
    fingerprint: Mapped[str] = mapped_column(String(64))
    chunk_config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    embedding_profile: Mapped[dict[str, Any]] = mapped_column(JSONB)
    chunk_count: Mapped[int] = mapped_column()
    indexed_count: Mapped[int] = mapped_column(default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="CHUNKED", server_default="CHUNKED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexChunk(Base):
    __tablename__ = "index_chunks"
    __table_args__ = (
        UniqueConstraint("index_revision_id", "position"),
        Index("ix_index_chunks_search_vector", "search_vector", postgresql_using="gin"),
        CheckConstraint("position >= 0 AND length(text) > 0", name="content_valid"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="hash_valid"),
        CheckConstraint(
            "jsonb_typeof(spans)='array' AND jsonb_array_length(spans)>0", name="spans_valid"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    index_revision_id: Mapped[UUID] = mapped_column(ForeignKey("index_revisions.id"), index=True)
    position: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    spans: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('spanish'::regconfig, text)", persisted=True)
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        CheckConstraint(
            "dimensions BETWEEN 1 AND 4096 AND vector_dims(embedding)=dimensions "
            "AND vector_norm(embedding)>0",
            name="vector_valid",
        ),
    )
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("index_chunks.id"), primary_key=True)
    dimensions: Mapped[int] = mapped_column()
    embedding: Mapped[list[float]] = mapped_column(VECTOR())


class EmbeddingCall(Base):
    """Successful batch receipts; unknown external costs remain NULL, never guessed as zero."""

    __tablename__ = "embedding_calls"
    __table_args__ = (
        CheckConstraint("chunk_count > 0 AND input_tokens >= 0", name="counts_valid"),
        CheckConstraint("observed_cost_usd >= 0", name="cost_valid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    index_revision_id: Mapped[UUID] = mapped_column(ForeignKey("index_revisions.id"), index=True)
    chunk_count: Mapped[int] = mapped_column()
    input_tokens: Mapped[int | None] = mapped_column()
    observed_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


for model in [Document, IndexRevision, IndexChunk, ChunkEmbedding]:
    event.listen(model.__table__, "after_create", install_invariant)
