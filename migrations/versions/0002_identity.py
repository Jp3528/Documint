"""Users and revocable session families with hashed single-use refresh tokens."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="status_valid"),
        sa.CheckConstraint("email = lower(trim(email))", name="email_normalized"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "refresh_tokens",
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("digest"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"]),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("users")
