"""Immutable chunks, physical vectors and verified atomic revision activation."""

from typing import cast

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects.postgresql import JSONB

from packages.documents.models import Document
from packages.indexing.invariants import install_invariant
from packages.indexing.models import ChunkEmbedding, IndexChunk, IndexRevision

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "index_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("chunk_config", JSONB(), nullable=False),
        sa.Column("embedding_profile", JSONB(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="CHUNKED"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "generation > 0 AND chunk_count > 0 AND indexed_count BETWEEN 0 AND chunk_count",
            name="counts_valid",
        ),
        sa.CheckConstraint(
            "status IN ('CHUNKED','INDEXING','READY','FAILED')", name="status_valid"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["extraction_id"], ["extractions.id"]),
        sa.UniqueConstraint("version_id", "fingerprint", name="uq_index_revision_fingerprint"),
        sa.UniqueConstraint("version_id", "generation", name="uq_index_revision_generation"),
    )
    op.create_index("ix_index_revisions_version_id", "index_revisions", ["version_id"])
    op.create_table(
        "index_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("index_revision_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("spans", JSONB(), nullable=False),
        sa.CheckConstraint("position >= 0 AND length(text) > 0", name="content_valid"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="hash_valid"),
        sa.CheckConstraint(
            "jsonb_typeof(spans)='array' AND jsonb_array_length(spans)>0", name="spans_valid"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["index_revision_id"], ["index_revisions.id"]),
        sa.UniqueConstraint("index_revision_id", "position"),
    )
    op.create_index("ix_index_chunks_index_revision_id", "index_chunks", ["index_revision_id"])
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.CheckConstraint(
            "dimensions BETWEEN 1 AND 4096 AND vector_dims(embedding)=dimensions "
            "AND vector_norm(embedding)>0",
            name="vector_valid",
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.ForeignKeyConstraint(["chunk_id"], ["index_chunks.id"]),
    )
    op.add_column("documents", sa.Column("active_index_revision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_documents_active_index_revision",
        "documents",
        "index_revisions",
        ["active_index_revision_id"],
        ["id"],
    )
    for model in [Document, IndexRevision, IndexChunk, ChunkEmbedding]:
        install_invariant(cast(sa.Table, model.__table__), op.get_bind())


def downgrade() -> None:
    op.execute("DROP TRIGGER guard_active_revision ON documents")
    op.drop_constraint("fk_documents_active_index_revision", "documents", type_="foreignkey")
    op.drop_column("documents", "active_index_revision_id")
    op.drop_table("chunk_embeddings")
    op.drop_table("index_chunks")
    op.drop_table("index_revisions")
    for name in ["guard_active_revision", "guard_index_ready", "immutable_index_row"]:
        op.execute(f"DROP FUNCTION {name}()")
