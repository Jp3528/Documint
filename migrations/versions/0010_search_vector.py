"""Versioned Spanish FTS vector for immutable chunks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_chunks",
        sa.Column(
            "search_vector",
            TSVECTOR,
            sa.Computed("to_tsvector('spanish'::regconfig, text)", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_index_chunks_search_vector", "index_chunks", ["search_vector"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_index_chunks_search_vector", table_name="index_chunks")
    op.drop_column("index_chunks", "search_vector")
