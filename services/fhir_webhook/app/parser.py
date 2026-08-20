from datetime import UTC, datetime

from services.fhir_webhook.app.models import FHIRWebhookEvent


class InvalidFHIRPayloadError(ValueError):
    pass


def parse_fhir_payload(payload: dict) -> FHIRWebhookEvent:
    resource_type = payload.get("resourceType")

    if not resource_type:
        raise InvalidFHIRPayloadError("FHIR payload does not contain resourceType")

    if resource_type != "Observation":
        raise InvalidFHIRPayloadError(f"Unsupported FHIR resource type: {resource_type}")

    return FHIRWebhookEvent(
        received_at=datetime.now(UTC),
        resource_type=resource_type,
        resource_id=payload.get("id"),
        payload=payload,
    )