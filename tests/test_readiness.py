from fastapi.testclient import TestClient

from job_automation.presentation.app import create_app


class HealthyProbe:
    async def check(self) -> None:
        return None


class UnavailableProbe:
    async def check(self) -> None:
        raise RuntimeError("database unavailable")


def test_health_does_not_call_dependencies() -> None:
    with TestClient(create_app(readiness_probe=UnavailableProbe())) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_success_for_healthy_probe() -> None:
    with TestClient(create_app(readiness_probe=HealthyProbe())) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_returns_stable_failure_for_unavailable_probe() -> None:
    with TestClient(create_app(readiness_probe=UnavailableProbe())) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
