from datetime import UTC, datetime

import pytest

from services.fhir_webhook.app.models import FHIRWebhookEvent
from services.fhir_webhook.app.vitals import transform_fhir_vitals
from testkit import expect


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

    expect.equal(result["observation_id"], "observation_123")
    expect.equal(result["patient_id"], "patient_123")
    expect.equal(result["encounter_id"], "encounter_456")
    expect.equal(result["schema_version"], "1.2")
    expect.equal(result["heart_rate"], 94.0)


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


def bedside_event(code: dict, value: dict) -> FHIRWebhookEvent:
    event = build_heart_rate_event()
    event.payload.pop("valueQuantity")
    event.payload["code"] = {"coding": [{"system": "http://loinc.org", **code}]}
    event.payload.update(value)
    return event


def test_temperature_and_inhaled_oxygen_become_event_fields() -> None:
    temperature = transform_fhir_vitals(bedside_event({"code": "8310-5"}, {"valueQuantity": {"value": 38.4, "unit": "Cel"}}))
    oxygen = transform_fhir_vitals(bedside_event({"code": "3150-0"}, {"valueQuantity": {"value": 28.0, "unit": "%"}}))

    expect.equal(temperature["temperature"], 38.4)
    expect.equal(oxygen["inhaled_oxygen_concentration"], 28.0)


def test_a_coded_acvpu_answer_becomes_its_ordinal() -> None:
    answer = {"valueCodeableConcept": {"coding": [{"system": "http://loinc.org", "code": "LA6560-2", "display": "Confused"}]}}

    result = transform_fhir_vitals(bedside_event({"code": "67775-7"}, answer))

    expect.equal(result["consciousness_level"], 1)


def test_an_unknown_acvpu_answer_is_rejected() -> None:
    answer = {"valueCodeableConcept": {"coding": [{"system": "http://loinc.org", "code": "LA25161-3", "display": "Lethargic"}]}}

    with pytest.raises(ValueError, match="67775-7"):
        transform_fhir_vitals(bedside_event({"code": "67775-7"}, answer))
