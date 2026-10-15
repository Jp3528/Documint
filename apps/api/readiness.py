"""Bounded probes report names and states only, never connection details or exceptions."""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from alembic.script import ScriptDirectory
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import text

from packages.config import Settings
from packages.database import make_engine
from packages.storage import S3Storage

type Probe = Callable[[], None]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, Literal["ok", "error"]]


def database_probe(settings: Settings) -> None:
    engine = make_engine(settings)
    try:
        with engine.connect() as conn:
            if (
                conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
                is None
            ):
                raise RuntimeError("vector extension missing")
            scripts = ScriptDirectory(str(Path(__file__).resolve().parents[2] / "migrations"))
            actual = set(conn.scalars(text("SELECT version_num FROM alembic_version")))
            if actual != set(scripts.get_heads()):
                raise RuntimeError("schema not current")
    finally:
        engine.dispose()


def redis_probe(settings: Settings) -> None:
    with Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2) as client:
        if not client.ping():
            raise RuntimeError("redis unavailable")


def dependency_probes(settings: Settings) -> dict[str, Probe]:
    return {
        "database": lambda: database_probe(settings),
        "redis": lambda: redis_probe(settings),
        "storage": lambda: S3Storage(settings).check_ready(),
    }


def evaluate(probes: dict[str, Probe]) -> ReadinessResponse:
    states: dict[str, Literal["ok", "error"]] = {}
    for name, probe in probes.items():
        try:
            probe()
            states[name] = "ok"
        except Exception:
            states[name] = "error"
    return ReadinessResponse(
        status="ready" if all(state == "ok" for state in states.values()) else "not_ready",
        dependencies=states,
    )
