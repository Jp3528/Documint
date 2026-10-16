"""Document visibility, archive state and explicit user/role grants."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("archived", sa.Boolean(), nullable=False, server_default="false")
    )
    op.create_check_constraint(
        "department_required",
        "documents",
        "visibility != 'DEPARTMENT' OR department_id IS NOT NULL",
    )
    op.create_table(
        "document_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role_name", sa.String(32), nullable=True),
        sa.Column("permission", sa.String(8), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("(user_id IS NOT NULL) != (role_name IS NOT NULL)", name="one_subject"),
        sa.CheckConstraint("permission IN ('READ', 'MANAGE')", name="permission_valid"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["role_name"], ["roles.name"]),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.UniqueConstraint("document_id", "user_id", name="uq_document_grants_user"),
        sa.UniqueConstraint("document_id", "role_name", name="uq_document_grants_role"),
    )
    op.create_index("ix_document_grants_document_id", "document_grants", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_grants")
    op.drop_constraint("ck_documents_department_required", "documents", type_="check")
    op.drop_column("documents", "archived")
