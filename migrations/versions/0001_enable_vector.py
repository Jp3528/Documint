"""Enable pgvector on an empty PostgreSQL database."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Do not drop a shared extension or cascade away stored evidence.
    pass
