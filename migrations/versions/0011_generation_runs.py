"""Private generation receipts and immutable source lineage, without storing prompts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("model_info", JSONB(), nullable=False),
        sa.Column("retrieval_config", JSONB(), nullable=False),
        sa.Column("usage", JSONB(), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("context_token_upper_bound", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(48)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('ANSWERED','ABSTAINED','FAILED')", name="status_valid"),
        sa.CheckConstraint("question_sha256 ~ '^[0-9a-f]{64}$'", name="question_hash_valid"),
    )
    op.create_index("ix_generation_runs_actor_id", "generation_runs", ["actor_id"])
    op.create_table(
        "generation_sources",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("generation_runs.id"), primary_key=True),
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("index_chunks.id"), primary_key=True),
        sa.Column("cited", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("generation_sources")
    op.drop_table("generation_runs")
