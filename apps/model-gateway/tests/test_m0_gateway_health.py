"""M0 acceptance criterion: model-gateway GET /health returns the shared HealthStatus contract."""

from fastapi.testclient import TestClient

from rpim_model_gateway.main import app


def test_m0_health_returns_200():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_m0_health_response_body_matches_contract():
    client = TestClient(app)
    response = client.get("/health")
    assert response.json() == {
        "status": "ok",
        "service": "model-gateway",
        "leg": "us",
    }
