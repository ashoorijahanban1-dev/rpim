from rpim_shared import HealthStatus


def test_health_status_defaults():
    h = HealthStatus(service="core-api", leg="iran")
    assert h.status == "ok"
    assert h.model_dump() == {"status": "ok", "service": "core-api", "leg": "iran"}


def test_health_status_leg_optional():
    h = HealthStatus(service="dashboard")
    assert h.leg is None
