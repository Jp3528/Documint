"""Private documents and immutable original version metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="RESTRICTED"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "visibility IN ('COMPANY', 'DEPARTMENT', 'RESTRICTED')", name="visibility_valid"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
    )
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="UPLOADING"),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version_number > 0", name="version_positive"),
        sa.CheckConstraint("size_bytes > 0", name="size_positive"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_valid"),
        sa.CheckConstraint(
            "status IN ('UPLOADING','UPLOAD_FAILED','UPLOADED','QUEUED','EXTRACTING',"
            "'CHUNKING','EMBEDDING','INDEXING','READY','FAILED')",
            name="status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.UniqueConstraint("document_id", "version_number"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_versions")
    op.drop_table("documents")
