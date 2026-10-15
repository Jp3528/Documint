import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.readiness import Probe, evaluate
from packages.config import Settings


def succeed() -> None:
    pass


def fail() -> None:
    raise RuntimeError("postgresql://secret-user:secret-password@private-host")


@pytest.mark.parametrize("failed", ["database", "redis", "storage"])
def test_each_dependency_failure_returns_503_without_connection_details(
    monkeypatch: pytest.MonkeyPatch, failed: str
) -> None:
    probes = {
        name: fail if name == failed else succeed for name in ("database", "redis", "storage")
    }
    monkeypatch.setattr("apps.api.main.dependency_probes", lambda _: probes)
    with TestClient(create_app(Settings())) as client:
        response = client.get("/ready")
        assert client.get("/health").status_code == 200
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["dependencies"][failed] == "error"
    assert "secret" not in response.text
    assert "private-host" not in response.text


def test_all_dependencies_are_probed_even_when_the_first_fails() -> None:
    calls: list[str] = []

    def record() -> None:
        calls.append("storage")

    probes: dict[str, Probe] = {"database": fail, "redis": succeed, "storage": record}
    report = evaluate(probes)
    assert calls == ["storage"]
    assert report.dependencies == {"database": "error", "redis": "ok", "storage": "ok"}


def test_readiness_success_is_a_distinct_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.api.main.dependency_probes",
        lambda _: {name: succeed for name in ("database", "redis", "storage")},
    )
    with TestClient(create_app(Settings())) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"database": "ok", "redis": "ok", "storage": "ok"},
    }
