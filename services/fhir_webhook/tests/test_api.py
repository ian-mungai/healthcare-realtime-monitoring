import os

from fastapi.testclient import TestClient

from services.fhir_webhook.app.main import app
from services.fhir_webhook.app.store import event_store

TEST_SECRET = "test_webhook_secret"

os.environ["FHIR_WEBHOOK_SECRET"] = TEST_SECRET

client = TestClient(app)


def setup_function():
    event_store.clear()


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_webhook_get_reachability():
    response = client.get("/webhooks/fhir")

    assert response.status_code == 200
    assert response.json()["status"] == "reachable"


def test_webhook_head_reachability():
    response = client.head("/webhooks/fhir")

    assert response.status_code == 200


def test_empty_handshake_is_accepted():
    response = client.post("/webhooks/fhir")

    assert response.status_code == 200
    assert response.json()["status"] == "handshake_accepted"


def test_webhook_requires_secret_for_observation():
    response = client.post("/webhooks/fhir", json={"resourceType": "Observation", "id": "observation_123"})

    assert response.status_code == 401


def test_webhook_accepts_observation():
    response = client.post(
        "/webhooks/fhir", headers={"X-Webhook-Secret": TEST_SECRET}, json={"resourceType": "Observation", "id": "observation_123", "status": "final"}
    )

    assert response.status_code == 202
    assert response.json()["resource_id"] == "observation_123"
    assert len(event_store.list_events()) == 1


def test_webhook_rejects_patient():
    response = client.post("/webhooks/fhir", headers={"X-Webhook-Secret": TEST_SECRET}, json={"resourceType": "Patient", "id": "patient_123"})

    assert response.status_code == 400


def test_list_events():
    client.post("/webhooks/fhir", headers={"X-Webhook-Secret": TEST_SECRET}, json={"resourceType": "Observation", "id": "observation_123"})

    response = client.get("/events")

    assert response.status_code == 200
    assert response.json()["count"] == 1
