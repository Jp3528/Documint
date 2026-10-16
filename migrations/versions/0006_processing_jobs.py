"""Durable, idempotent processing outbox and bounded dispatch attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="STORED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_dispatch_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','QUEUED','RUNNING','WAITING_PIPELINE','SUCCEEDED',"
            "'FAILED','DISPATCH_FAILED')",
            name="status_valid",
        ),
        sa.CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempts_valid"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 5", name="max_attempts_valid"),
        sa.CheckConstraint("dispatch_attempts BETWEEN 0 AND 5", name="dispatch_attempts_valid"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"]),
        sa.UniqueConstraint("version_id", "pipeline_key"),
    )
    op.create_index("ix_processing_jobs_version_id", "processing_jobs", ["version_id"])
    # Backfill original versions stored before the processing outbox existed.
    op.execute("""INSERT INTO processing_jobs (id, version_id, pipeline_key)
        SELECT gen_random_uuid(), id, 'text-v1' FROM document_versions
        WHERE status = 'UPLOADED'""")


def downgrade() -> None:
    op.drop_table("processing_jobs")
