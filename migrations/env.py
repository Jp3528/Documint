from alembic import context

from packages.config import get_settings
from packages.database import make_engine
from packages.documents.models import Document
from packages.identity.models import User  # noqa: F401
from packages.indexing.models import IndexRevision  # noqa: F401
from packages.parsers.models import Extraction  # noqa: F401
from packages.processing.models import ProcessingJob  # noqa: F401

settings = get_settings()

if context.is_offline_mode():
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=Document.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Document.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
