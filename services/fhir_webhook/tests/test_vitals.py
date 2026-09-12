from datetime import UTC, datetime

import pytest

from services.fhir_webhook.app.models import FHIRWebhookEvent
from services.fhir_webhook.app.vitals import transform_fhir_vitals


def build_heart_rate_event(resource_id: str | None = "observation_123") -> FHIRWebhookEvent:
    return FHIRWebhookEvent(
        received_at=datetime(2026, 9, 1, 15, 30, tzinfo=UTC),
        resource_type="Observation",
        resource_id=resource_id,
        payload={
            "resourceType": "Observation",
            "id": resource_id,
            "status": "final",
            "subject": {"reference": "Patient/patient_123"},
            "encounter": {"reference": "Encounter/encounter_456"},
            "effectiveDateTime": "2026-09-01T15:29:00Z",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
            "valueQuantity": {"value": 94.0, "unit": "beats/minute"},
        },
    )


def test_transform_fhir_vitals_preserves_observation_id() -> None:
    result = transform_fhir_vitals(build_heart_rate_event())

    assert result["observation_id"] == "observation_123"
    assert result["patient_id"] == "patient_123"
    assert result["encounter_id"] == "encounter_456"
    assert result["schema_version"] == "1.1"
    assert result["heart_rate"] == 94.0


def test_transform_fhir_vitals_rejects_missing_observation_id() -> None:
    with pytest.raises(ValueError, match="FHIR Observation identifier is required"):
        transform_fhir_vitals(build_heart_rate_event(resource_id=None))


def test_transform_fhir_vitals_rejects_missing_encounter_reference() -> None:
    event = build_heart_rate_event()
    event.payload.pop("encounter")

    with pytest.raises(ValueError, match="encounter must reference an Encounter"):
        transform_fhir_vitals(event)


@pytest.mark.parametrize("reference", [None, 123, "", "Encounter/", "EpisodeOfCare/encounter_456"])
def test_transform_fhir_vitals_rejects_invalid_encounter_reference(reference: object) -> None:
    event = build_heart_rate_event()
    event.payload["encounter"] = {"reference": reference}

    with pytest.raises(ValueError, match="encounter"):
        transform_fhir_vitals(event)
