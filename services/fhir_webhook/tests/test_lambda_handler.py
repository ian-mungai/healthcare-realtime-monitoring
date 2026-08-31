import json
import os
from unittest.mock import MagicMock, patch

from services.fhir_webhook.app.kinesis.client import KinesisPublisherError, KinesisPublishResult
from services.fhir_webhook.app.lambda_handler import lambda_handler

TEST_SECRET = "test_webhook_secret"

os.environ["FHIR_WEBHOOK_SECRET"] = TEST_SECRET
os.environ["KINESIS_STREAM_NAME"] = "healthcare_realtime_vitals"
os.environ["AWS_REGION"] = "us-east-1"


def test_health():
    response = lambda_handler({"routeKey": "GET /health"}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "healthy"


def test_webhook_get_reachability():
    response = lambda_handler({"routeKey": "GET /webhooks/fhir"}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "reachable"


def test_webhook_head_reachability():
    response = lambda_handler({"routeKey": "HEAD /webhooks/fhir"}, None)

    assert response["statusCode"] == 200


def test_empty_webhook_handshake():
    response = lambda_handler({"routeKey": "POST /webhooks/fhir", "body": "", "headers": {}}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "handshake_accepted"


def test_empty_bundle_handshake():
    response = lambda_handler({"routeKey": "POST /webhooks/fhir", "body": json.dumps({"resourceType": "Bundle", "entry": []}), "headers": {}}, None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "handshake_accepted"


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_observation_is_published(mock_publisher_class):
    publisher = MagicMock()
    publisher.publish.return_value = KinesisPublishResult(shard_id="shardId-000000000000", sequence_number="123456789", partition_key="Patient/patient_123")
    mock_publisher_class.return_value = publisher

    response = lambda_handler(
        {
            "routeKey": "POST /webhooks/fhir",
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps({"resourceType": "Observation", "id": "observation_123", "status": "final", "subject": {"reference": "Patient/patient_123"}}),
        },
        None,
    )

    assert response["statusCode"] == 202
    assert json.loads(response["body"])["resource_id"] == "observation_123"
    publisher.publish.assert_called_once()


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_observation_without_patient_reference_returns_400(mock_publisher_class):
    publisher = MagicMock()
    publisher.publish.side_effect = ValueError("FHIR Observation subject must reference a Patient")
    mock_publisher_class.return_value = publisher

    response = lambda_handler(
        {
            "routeKey": "POST /webhooks/fhir",
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps({"resourceType": "Observation", "id": "observation_123", "status": "final"}),
        },
        None,
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["detail"] == "FHIR Observation subject must reference a Patient"


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_unsupported_vital_returns_400(mock_publisher_class):
    publisher = MagicMock()
    publisher.publish.side_effect = ValueError("Unsupported FHIR vital Observation LOINC code: 1234-5")
    mock_publisher_class.return_value = publisher

    response = lambda_handler(
        {
            "routeKey": "POST /webhooks/fhir",
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps({"resourceType": "Observation", "id": "observation_123", "status": "final", "subject": {"reference": "Patient/patient_123"}}),
        },
        None,
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["detail"] == "Unsupported FHIR vital Observation LOINC code: 1234-5"


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_missing_vital_value_returns_400(mock_publisher_class):
    publisher = MagicMock()
    publisher.publish.side_effect = ValueError("FHIR Observation 8867-4 does not contain valueQuantity.value")
    mock_publisher_class.return_value = publisher

    response = lambda_handler(
        {
            "routeKey": "POST /webhooks/fhir",
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps({"resourceType": "Observation", "id": "observation_123", "status": "final", "subject": {"reference": "Patient/patient_123"}}),
        },
        None,
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["detail"] == "FHIR Observation 8867-4 does not contain valueQuantity.value"


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_kinesis_failure_returns_503(mock_publisher_class):
    publisher = MagicMock()
    publisher.publish.side_effect = KinesisPublisherError("test failure")
    mock_publisher_class.return_value = publisher

    response = lambda_handler(
        {
            "routeKey": "POST /webhooks/fhir",
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps({"resourceType": "Observation", "id": "observation_123", "status": "final", "subject": {"reference": "Patient/patient_123"}}),
        },
        None,
    )

    assert response["statusCode"] == 503
    assert json.loads(response["body"])["detail"] == "Kinesis ingestion failed"


def test_fhir_metadata():
    response = lambda_handler({"routeKey": "GET /webhooks/fhir/metadata"}, None)

    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "application/fhir+json"

    payload = json.loads(response["body"])

    assert payload["resourceType"] == "CapabilityStatement"
    assert payload["fhirVersion"] == "4.0.1"
    assert payload["rest"][0]["resource"][0]["type"] == "Observation"
    assert payload["rest"][0]["resource"][0]["interaction"] == [{"code": "update"}]


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_hapi_fhir_update_is_published(mock_publisher_class):
    publisher = MagicMock()
    publisher.publish.return_value = KinesisPublishResult(shard_id="shardId-000000000000", sequence_number="123456789", partition_key="patient_123")
    mock_publisher_class.return_value = publisher

    observation = {"resourceType": "Observation", "id": "observation_123", "status": "final", "subject": {"reference": "Patient/patient_123"}}

    response = lambda_handler(
        {
            "routeKey": "PUT /webhooks/fhir/{resource_type}/{resource_id}",
            "pathParameters": {"resource_type": "Observation", "resource_id": "observation_123"},
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps(observation),
        },
        None,
    )

    assert response["statusCode"] == 200
    assert response["headers"]["content-type"] == "application/fhir+json"
    assert json.loads(response["body"]) == observation
    publisher.publish.assert_called_once()


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_hapi_fhir_update_resource_type_mismatch_returns_400(mock_publisher_class):
    response = lambda_handler(
        {
            "routeKey": "PUT /webhooks/fhir/{resource_type}/{resource_id}",
            "pathParameters": {"resource_type": "Patient", "resource_id": "observation_123"},
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps({"resourceType": "Observation", "id": "observation_123", "status": "final"}),
        },
        None,
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["detail"] == "FHIR resource type does not match request path"
    mock_publisher_class.assert_not_called()


@patch("services.fhir_webhook.app.lambda_handler.KinesisPublisher")
def test_hapi_fhir_update_resource_id_mismatch_returns_400(mock_publisher_class):
    response = lambda_handler(
        {
            "routeKey": "PUT /webhooks/fhir/{resource_type}/{resource_id}",
            "pathParameters": {"resource_type": "Observation", "resource_id": "observation_456"},
            "headers": {"x-webhook-secret": TEST_SECRET},
            "body": json.dumps({"resourceType": "Observation", "id": "observation_123", "status": "final"}),
        },
        None,
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["detail"] == "FHIR resource identifier does not match request path"
    mock_publisher_class.assert_not_called()
