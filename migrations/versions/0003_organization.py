"""Roles, departments and unique memberships."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    roles = op.create_table(
        "roles",
        sa.Column("name", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "name IN ('ADMIN', 'KNOWLEDGE_MANAGER', 'EMPLOYEE', 'AUDITOR')", name="name_valid"
        ),
        sa.PrimaryKeyConstraint("name"),
    )
    op.bulk_insert(
        roles, [{"name": name} for name in ("ADMIN", "KNOWLEDGE_MANAGER", "EMPLOYEE", "AUDITOR")]
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_name", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_name"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["role_name"], ["roles.name"]),
    )
    # Existing non-demo users receive the least privileged functional role.
    op.execute("INSERT INTO user_roles (user_id, role_name) SELECT id, 'EMPLOYEE' FROM users")
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.CheckConstraint("code = upper(trim(code))", name="code_normalized"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "department_members",
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("membership_role", sa.String(16), nullable=False, server_default="MEMBER"),
        sa.CheckConstraint(
            "membership_role IN ('MEMBER', 'MANAGER')", name="membership_role_valid"
        ),
        sa.PrimaryKeyConstraint("department_id", "user_id"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )


def downgrade() -> None:
    op.drop_table("department_members")
    op.drop_table("departments")
    op.drop_table("user_roles")
    op.drop_table("roles")
