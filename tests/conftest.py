"""Real PostgreSQL fixtures use a disposable transactional schema, never demo identities."""

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from packages.config import Settings
from packages.database import Base, make_engine
from packages.identity.models import Role
from packages.identity.policies import RoleName


@pytest.fixture
def isolated_db() -> Iterator[sessionmaker[Session]]:
    if os.getenv("DOCUMIND_TEST_INFRA") != "1":
        pytest.skip("requires the migrated PostgreSQL from Compose")
    engine = make_engine(Settings())
    schema = "test_" + uuid4().hex
    connection = engine.connect().execution_options(schema_translate_map={None: schema})
    transaction = connection.begin()
    try:
        connection.execute(CreateSchema(schema))
        # Migrations are tested separately on an empty DB in CI. Runtime never creates tables.
        Base.metadata.create_all(connection)
        factory = sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        with factory() as db:
            db.add_all(Role(name=role.value) for role in RoleName)
            db.commit()
        yield factory
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def concurrent_db() -> Iterator[sessionmaker[Session]]:
    """Committed disposable schema; each concurrent task gets an independent connection."""
    if os.getenv("DOCUMIND_TEST_INFRA") != "1":
        pytest.skip("requires PostgreSQL infrastructure")
    engine = make_engine(Settings())
    schema = "test_concurrent_" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            Base.metadata.create_all(
                connection.execution_options(schema_translate_map={None: schema})
            )
        factory = sessionmaker(
            bind=engine.execution_options(schema_translate_map={None: schema}),
            expire_on_commit=False,
        )
        with factory() as db:
            db.add_all(Role(name=role.value) for role in RoleName)
            db.commit()
        yield factory
    finally:
        assert schema.startswith("test_concurrent_") and len(schema) == 48
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        engine.dispose()
