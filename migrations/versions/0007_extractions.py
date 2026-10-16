"""Normalized extraction snapshots with reproducible parser revision and source locators."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("parser_revision", sa.String(128), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_sha256", sa.String(64), nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("blocks", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("block_count > 0 AND character_count > 0", name="counts_positive"),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$' AND normalized_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"]),
        sa.UniqueConstraint("version_id", "parser_revision"),
    )
    op.create_index("ix_extractions_version_id", "extractions", ["version_id"])


def downgrade() -> None:
    op.drop_table("extractions")
