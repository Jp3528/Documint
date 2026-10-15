from alembic import context

from packages.config import get_settings
from packages.database import make_engine
from packages.identity.models import User

settings = get_settings()

if context.is_offline_mode():
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=User.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=User.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
