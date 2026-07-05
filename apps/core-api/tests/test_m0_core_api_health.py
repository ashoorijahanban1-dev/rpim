"""M0 acceptance criterion: core-api GET /health returns the shared HealthStatus contract."""

from fastapi.testclient import TestClient

from rpim_core_api.main import app


def test_m0_health_returns_200():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_m0_health_response_body_matches_contract():
    client = TestClient(app)
    response = client.get("/health")
    assert response.json() == {
        "status": "ok",
        "service": "core-api",
        "leg": "iran",
    }
