import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from services.fhir_webhook.app.kinesis.client import KinesisPublisherError, KinesisPublishResult
from services.fhir_webhook.app.main import app

TEST_SECRET = "test_webhook_secret"

os.environ["FHIR_WEBHOOK_SECRET"] = TEST_SECRET
os.environ["KINESIS_STREAM_NAME"] = "healthcare_realtime_vitals"
os.environ["AWS_REGION"] = "us-east-1"

client = TestClient(app)


def build_publish_result() -> KinesisPublishResult:
    return KinesisPublishResult(shard_id="shardId-000000000000", sequence_number="123456789", partition_key="patient_123")


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "fhir_webhook"}


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


def test_empty_bundle_handshake_is_accepted():
    response = client.post("/webhooks/fhir", json={"resourceType": "Bundle", "entry": []})

    assert response.status_code == 200
    assert response.json()["status"] == "handshake_accepted"


def test_webhook_requires_valid_json():
    response = client.post("/webhooks/fhir", headers={"X-Webhook-Secret": TEST_SECRET, "Content-Type": "application/json"}, content="not-json")

    assert response.status_code == 400
    assert response.json()["detail"] == "Request body must contain valid JSON"


def test_webhook_requires_secret():
    response = client.post("/webhooks/fhir", json={"resourceType": "Observation", "id": "observation_123", "status": "final"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook secret"


@patch("services.fhir_webhook.app.main.KinesisPublisher")
def test_webhook_accepts_observation(mock_publisher_class):
    mock_publisher = MagicMock()
    mock_publisher.publish.return_value = build_publish_result()
    mock_publisher_class.return_value = mock_publisher

    response = client.post(
        "/webhooks/fhir",
        headers={"X-Webhook-Secret": TEST_SECRET},
        json={"resourceType": "Observation", "id": "observation_123", "status": "final", "subject": {"reference": "Patient/patient_123"}},
    )

    assert response.status_code == 202

    body = response.json()

    assert body["status"] == "accepted"
    assert body["resource_type"] == "Observation"
    assert body["resource_id"] == "observation_123"
    assert body["shard_id"] == "shardId-000000000000"
    assert body["sequence_number"] == "123456789"

    mock_publisher.publish.assert_called_once()


def test_webhook_rejects_patient():
    response = client.post("/webhooks/fhir", headers={"X-Webhook-Secret": TEST_SECRET}, json={"resourceType": "Patient", "id": "patient_123"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported FHIR resource type: Patient"


@patch("services.fhir_webhook.app.main.KinesisPublisher")
def test_webhook_returns_503_when_kinesis_publish_fails(mock_publisher_class):
    mock_publisher = MagicMock()
    mock_publisher.publish.side_effect = KinesisPublisherError("test failure")
    mock_publisher_class.return_value = mock_publisher

    response = client.post(
        "/webhooks/fhir",
        headers={"X-Webhook-Secret": TEST_SECRET},
        json={"resourceType": "Observation", "id": "observation_123", "status": "final", "subject": {"reference": "Patient/patient_123"}},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Kinesis ingestion failed"
