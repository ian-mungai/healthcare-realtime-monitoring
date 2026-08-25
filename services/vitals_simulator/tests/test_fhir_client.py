import httpx
import pytest
import respx

from services.vitals_simulator.app.fhir.client import FHIRPermanentError, HAPIFHIRClient

FHIR_BASE_URL = "https://hapi.fhir.org/baseR4"


def sample_observation() -> dict:
    return {
        "resourceType": "Observation",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
        "subject": {"reference": "Patient/123"},
        "valueQuantity": {"value": 94.0, "unit": "beats/minute", "system": "http://unitsofmeasure.org", "code": "/min"},
    }


@respx.mock
def test_post_resource_returns_created_resource():
    respx.post(f"{FHIR_BASE_URL}/Observation").mock(return_value=httpx.Response(201, json={"resourceType": "Observation", "id": "observation_123"}, headers={"Location": "Observation/observation_123/_history/1"}))

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)
    created = client.post_resource(sample_observation())

    assert created.resource_type == "Observation"
    assert created.resource_id == "observation_123"
    assert created.status_code == 201


@respx.mock
def test_post_resource_rejects_permanent_error():
    respx.post(f"{FHIR_BASE_URL}/Observation").mock(return_value=httpx.Response(400, json={"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "processing", "diagnostics": "Invalid Observation"}]}))

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)

    with pytest.raises(FHIRPermanentError, match="Invalid Observation"):
        client.post_resource(sample_observation())


def test_post_resource_requires_resource_type():
    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)

    with pytest.raises(ValueError, match="resourceType"):
        client.post_resource({})


@respx.mock
def test_post_resource_retries_transient_failure():
    route = respx.post(f"{FHIR_BASE_URL}/Observation").mock(side_effect=[httpx.Response(503), httpx.Response(201, json={"resourceType": "Observation", "id": "observation_456"})])

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=3, retry_delay_seconds=0)
    created = client.post_resource(sample_observation())

    assert route.call_count == 2
    assert created.resource_id == "observation_456"


@respx.mock
def test_post_resource_does_not_retry_bad_request():
    route = respx.post(f"{FHIR_BASE_URL}/Observation").mock(return_value=httpx.Response(400, json={"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "processing", "diagnostics": "Bad request"}]}))

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=3, retry_delay_seconds=0)

    with pytest.raises(FHIRPermanentError):
        client.post_resource(sample_observation())

    assert route.call_count == 1


def test_build_headers_adds_conditional_create():
    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)

    observation = sample_observation()
    observation["identifier"] = [{"system": "https://example.org/fhir/identifier/vitals-simulator", "value": "abc123"}]

    headers = client._build_headers(observation)

    assert "If-None-Exist" in headers
    assert "abc123" in headers["If-None-Exist"]
