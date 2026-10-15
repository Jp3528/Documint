from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_health_reports_liveness_without_dependency_connections() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "documind-api", "version": "0.1.0"}


def test_health_contract_is_documented_in_openapi() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
    assert schema["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/HealthResponse")
