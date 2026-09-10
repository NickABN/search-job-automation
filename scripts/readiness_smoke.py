from fastapi.testclient import TestClient

from job_automation.presentation.app import create_app

with TestClient(create_app()) as client:
    response = client.get("/ready")
    response.raise_for_status()
    assert response.json() == {"status": "ready"}
print("readiness smoke: ready")
