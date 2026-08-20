import pytest

from services.fhir_webhook.app.parser import InvalidFHIRPayloadError, parse_fhir_payload


def test_parse_observation():
    payload = {
        "resourceType": "Observation",
        "id": "observation_123",
        "status": "final",
    }

    event = parse_fhir_payload(payload)

    assert event.resource_type == "Observation"
    assert event.resource_id == "observation_123"
    assert event.payload == payload


def test_reject_missing_resource_type():
    with pytest.raises(InvalidFHIRPayloadError, match="resourceType"):
        parse_fhir_payload({})


def test_reject_non_observation():
    payload = {
        "resourceType": "Patient",
        "id": "patient_123",
    }

    with pytest.raises(InvalidFHIRPayloadError, match="Unsupported"):
        parse_fhir_payload(payload)