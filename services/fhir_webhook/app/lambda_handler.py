import base64
import json

from services.fhir_webhook.app.kinesis.client import KinesisPublisher, KinesisPublisherError
from services.fhir_webhook.app.parser import InvalidFHIRPayloadError, parse_fhir_payload
from services.fhir_webhook.app.security import WEBHOOK_SECRET_HEADER, validate_webhook_secret

FHIR_WEBHOOK_ROUTE = "POST /webhooks/fhir"
FHIR_UPDATE_ROUTE = "PUT /webhooks/fhir/{resource_type}/{resource_id}"
FHIR_METADATA_ROUTE = "GET /webhooks/fhir/metadata"


def build_response(status_code: int, body: dict | None = None, content_type: str = "application/json") -> dict:
    response = {"statusCode": status_code, "headers": {"content-type": content_type}}
    if body is not None:
        response["body"] = json.dumps(body)
    return response


def build_capability_statement() -> dict:
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "kind": "instance",
        "fhirVersion": "4.0.1",
        "format": ["application/fhir+json"],
        "rest": [{"mode": "server", "resource": [{"type": "Observation", "interaction": [{"code": "update"}]}]}],
    }


def get_header(headers: dict, name: str) -> str | None:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            return value
    return None


def decode_body(event: dict) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode("utf-8")
    return body


def validate_update_path(event: dict, payload: dict) -> str | None:
    path_parameters = event.get("pathParameters") or {}
    resource_type = path_parameters.get("resource_type")
    resource_id = path_parameters.get("resource_id")

    if payload.get("resourceType") != resource_type:
        return "FHIR resource type does not match request path"

    if payload.get("id") != resource_id:
        return "FHIR resource identifier does not match request path"

    return None


def lambda_handler(event: dict, context) -> dict:
    route_key = event.get("routeKey")

    if route_key == "GET /health":
        return build_response(200, {"status": "healthy", "service": "fhir_webhook"})

    if route_key == "GET /webhooks/fhir":
        return build_response(200, {"status": "reachable"})

    if route_key == "HEAD /webhooks/fhir":
        return build_response(200)

    if route_key == FHIR_METADATA_ROUTE:
        return build_response(200, build_capability_statement(), "application/fhir+json")

    if route_key not in {FHIR_WEBHOOK_ROUTE, FHIR_UPDATE_ROUTE}:
        return build_response(404, {"detail": "Route not found"})

    body = decode_body(event)

    if route_key == FHIR_WEBHOOK_ROUTE and not body.strip():
        return build_response(200, {"status": "handshake_accepted"})

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return build_response(400, {"detail": "Request body must contain valid JSON"})

    if not isinstance(payload, dict):
        return build_response(400, {"detail": "Request body must contain a JSON object"})

    if route_key == FHIR_WEBHOOK_ROUTE and payload.get("resourceType") == "Bundle" and not payload.get("entry"):
        return build_response(200, {"status": "handshake_accepted"})

    headers = event.get("headers") or {}
    received_secret = get_header(headers, WEBHOOK_SECRET_HEADER)

    try:
        secret_valid = validate_webhook_secret(received_secret)
    except RuntimeError:
        return build_response(500, {"detail": "Webhook secret is not configured"})

    if not secret_valid:
        return build_response(401, {"detail": "Invalid webhook secret"})

    if route_key == FHIR_UPDATE_ROUTE:
        path_error = validate_update_path(event, payload)
        if path_error:
            return build_response(400, {"detail": path_error})

    try:
        webhook_event = parse_fhir_payload(payload)
    except InvalidFHIRPayloadError as error:
        return build_response(400, {"detail": str(error)})

    try:
        publisher = KinesisPublisher()
        result = publisher.publish(webhook_event)
    except ValueError as error:
        return build_response(400, {"detail": str(error)})
    except KinesisPublisherError:
        return build_response(503, {"detail": "Kinesis ingestion failed"})

    if route_key == FHIR_UPDATE_ROUTE:
        return build_response(200, payload, "application/fhir+json")

    return build_response(
        202,
        {
            "status": "accepted",
            "resource_type": webhook_event.resource_type,
            "resource_id": webhook_event.resource_id,
            "shard_id": result.shard_id,
            "sequence_number": result.sequence_number,
        },
    )
