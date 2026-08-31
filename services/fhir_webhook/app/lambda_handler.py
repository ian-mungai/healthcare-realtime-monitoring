import base64
import json

from services.fhir_webhook.app.kinesis.client import KinesisPublisher, KinesisPublisherError
from services.fhir_webhook.app.parser import InvalidFHIRPayloadError, parse_fhir_payload
from services.fhir_webhook.app.security import WEBHOOK_SECRET_HEADER, validate_webhook_secret


def build_response(status_code: int, body: dict | None = None) -> dict:
    response = {"statusCode": status_code, "headers": {"content-type": "application/json"}}

    if body is not None:
        response["body"] = json.dumps(body)

    return response


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


def lambda_handler(event: dict, context) -> dict:
    route_key = event.get("routeKey")

    if route_key == "GET /health":
        return build_response(200, {"status": "healthy", "service": "fhir_webhook"})

    if route_key == "GET /webhooks/fhir":
        return build_response(200, {"status": "reachable"})

    if route_key == "HEAD /webhooks/fhir":
        return build_response(200)

    if route_key != "POST /webhooks/fhir":
        return build_response(404, {"detail": "Route not found"})

    body = decode_body(event)

    if not body.strip():
        return build_response(200, {"status": "handshake_accepted"})

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return build_response(400, {"detail": "Request body must contain valid JSON"})

    if not isinstance(payload, dict):
        return build_response(400, {"detail": "Request body must contain a JSON object"})

    if payload.get("resourceType") == "Bundle" and not payload.get("entry"):
        return build_response(200, {"status": "handshake_accepted"})

    headers = event.get("headers") or {}
    received_secret = get_header(headers, WEBHOOK_SECRET_HEADER)

    try:
        secret_valid = validate_webhook_secret(received_secret)
    except RuntimeError:
        return build_response(500, {"detail": "Webhook secret is not configured"})

    if not secret_valid:
        return build_response(401, {"detail": "Invalid webhook secret"})

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
