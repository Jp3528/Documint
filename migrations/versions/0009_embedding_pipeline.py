"""Embedding receipts and fenced, recoverable processing runs."""

from typing import cast

import sqlalchemy as sa
from alembic import op

from packages.indexing.invariants import install_invariant
from packages.indexing.models import ChunkEmbedding, IndexRevision

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_jobs", sa.Column("run_token", sa.Uuid(), nullable=True))
    op.add_column("processing_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("processing_jobs", sa.Column("index_revision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_processing_jobs_index_revision_id_index_revisions",
        "processing_jobs",
        "index_revisions",
        ["index_revision_id"],
        ["id"],
    )
    op.create_table(
        "embedding_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "index_revision_id", sa.Uuid(), sa.ForeignKey("index_revisions.id"), nullable=False
        ),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("observed_cost_usd", sa.Numeric(20, 10), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("chunk_count > 0 AND input_tokens >= 0", name="counts_valid"),
        sa.CheckConstraint("observed_cost_usd >= 0", name="cost_valid"),
    )
    op.create_index(
        "ix_embedding_calls_index_revision_id", "embedding_calls", ["index_revision_id"]
    )
    install_invariant(cast(sa.Table, ChunkEmbedding.__table__), op.get_bind())
    install_invariant(cast(sa.Table, IndexRevision.__table__), op.get_bind())


def downgrade() -> None:
    op.drop_table("embedding_calls")
    op.drop_constraint(
        "fk_processing_jobs_index_revision_id_index_revisions",
        "processing_jobs",
        type_="foreignkey",
    )
    for name in ["index_revision_id", "lease_expires_at", "run_token"]:
        op.drop_column("processing_jobs", name)
