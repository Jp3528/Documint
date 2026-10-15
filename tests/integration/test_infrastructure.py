"""Opt-in real infrastructure. No replacement by mocks when services are unavailable."""

import os
from uuid import uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from apps.api.main import create_app
from apps.worker.celery_app import create_celery_app
from apps.worker.tasks import smoke
from packages.config import Settings
from packages.database import make_engine
from packages.storage import S3Storage

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.skipif(
        os.getenv("DOCUMIND_TEST_INFRA") != "1",
        reason="Set DOCUMIND_TEST_INFRA=1 after Compose, migrations and storage bootstrap",
    ),
]


def test_migration_and_pgvector_distance() -> None:
    engine = make_engine(Settings())
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
            assert conn.scalar(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")) == 1.0
    finally:
        engine.dispose()


def test_s3_binary_roundtrip_and_delete() -> None:
    storage = S3Storage(Settings())
    key = f"smoke/{uuid4().hex}/file.txt"
    content = "Documento sintético con ñ y acentos.\n".encode() + b"\x00\xff"
    try:
        storage.put(key, content, "application/octet-stream")
        assert storage.get(key) == content
    finally:
        storage.delete(key)
    assert storage.client.list_objects_v2(Bucket=storage.bucket, Prefix=key)["KeyCount"] == 0


def test_readiness_against_real_services() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/ready")
    assert response.status_code == 200, response.text
    assert set(response.json()["dependencies"].values()) == {"ok"}


@pytest.mark.parametrize("dependency", ["database", "redis", "storage"])
def test_actual_connection_failure_is_isolated(dependency: str) -> None:
    settings = Settings()
    if dependency == "database":
        settings.database_url = SecretStr("postgresql+psycopg://demo:private@127.0.0.1:1/documind")
    elif dependency == "redis":
        settings.redis_url = "redis://127.0.0.1:1/0"
    else:
        settings.s3_endpoint = "http://127.0.0.1:1"
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
        assert client.get("/health").status_code == 200
    assert response.status_code == 503
    assert response.json()["dependencies"] == {
        name: "error" if name == dependency else "ok" for name in ("database", "redis", "storage")
    }
    assert "private" not in response.text


def test_real_redis_worker_roundtrip() -> None:
    settings = Settings()
    celery_app = create_celery_app(settings)
    smoke_task = celery_app.task(name="documind.redis_smoke")(smoke)
    with start_worker(celery_app, pool="solo", perform_ping_check=False, shutdown_timeout=10):
        result = smoke_task.delay("redis-smoke")
        try:
            assert result.get(timeout=10) == {
                "status": "ok",
                "service": "documind-worker",
                "message": "redis-smoke",
            }
        finally:
            result.forget()
