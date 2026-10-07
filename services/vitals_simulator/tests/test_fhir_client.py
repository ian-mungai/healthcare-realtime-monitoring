import json

import httpx
import pytest
import respx

from services.vitals_simulator.app.fhir.client import FHIRClientError, FHIRPermanentError, HAPIFHIRClient
from testkit import expect

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
    respx.post(f"{FHIR_BASE_URL}/Observation").mock(
        return_value=httpx.Response(
            201, json={"resourceType": "Observation", "id": "observation_123"}, headers={"Location": "Observation/observation_123/_history/1"}
        )
    )

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)
    created = client.post_resource(sample_observation())

    expect.equal(created.resource_type, "Observation")
    expect.equal(created.resource_id, "observation_123")
    expect.equal(created.status_code, 201)


@respx.mock
def test_post_resource_rejects_permanent_error():
    respx.post(f"{FHIR_BASE_URL}/Observation").mock(
        return_value=httpx.Response(
            400, json={"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "processing", "diagnostics": "Invalid Observation"}]}
        )
    )

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)

    with pytest.raises(FHIRPermanentError, match="Invalid Observation"):
        client.post_resource(sample_observation())


def test_post_resource_requires_resource_type():
    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)

    with pytest.raises(ValueError, match="resourceType"):
        client.post_resource({})


@respx.mock
def test_post_resource_retries_transient_failure():
    route = respx.post(f"{FHIR_BASE_URL}/Observation").mock(
        side_effect=[httpx.Response(503), httpx.Response(201, json={"resourceType": "Observation", "id": "observation_456"})]
    )

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=3, retry_delay_seconds=0)
    created = client.post_resource(sample_observation())

    expect.equal(route.call_count, 2)
    expect.equal(created.resource_id, "observation_456")


@respx.mock
def test_post_resource_does_not_retry_bad_request():
    route = respx.post(f"{FHIR_BASE_URL}/Observation").mock(
        return_value=httpx.Response(
            400, json={"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "processing", "diagnostics": "Bad request"}]}
        )
    )

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=3, retry_delay_seconds=0)

    with pytest.raises(FHIRPermanentError):
        client.post_resource(sample_observation())

    expect.equal(route.call_count, 1)


def test_build_headers_adds_conditional_create():
    client = HAPIFHIRClient(base_url=FHIR_BASE_URL)

    observation = sample_observation()
    observation["identifier"] = [{"system": "https://example.org/fhir/identifier/vitals-simulator", "value": "abc123"}]

    headers = client._build_headers(observation)

    expect.is_in("If-None-Exist", headers)
    expect.is_in("abc123", headers["If-None-Exist"])


@respx.mock
def test_count_resources_uses_a_retried_summary_search():
    route = respx.get(f"{FHIR_BASE_URL}/Encounter", params={"subject": "Patient/1000", "_tag": "system|normal", "_summary": "count"}).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"resourceType": "Bundle", "type": "searchset", "total": 2})]
    )

    client = HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=3, retry_delay_seconds=0)

    expect.equal(client.count_resources("Encounter", {"subject": "Patient/1000", "_tag": "system|normal"}), 2)
    expect.equal(route.call_count, 2)


@respx.mock
def test_count_resources_rejects_a_response_without_total():
    respx.get(f"{FHIR_BASE_URL}/Encounter").mock(return_value=httpx.Response(200, json={"resourceType": "Bundle"}))

    with pytest.raises(FHIRClientError, match="total"):
        HAPIFHIRClient(base_url=FHIR_BASE_URL).count_resources("Encounter", {"subject": "Patient/1000"})


@respx.mock
def test_upsert_resource_updates_the_resource_with_the_same_identifier():
    # A rerun with changed admission logic must update the encounter it created before, not keep the old one.
    route = respx.put(f"{FHIR_BASE_URL}/Encounter").mock(return_value=httpx.Response(200, json={"resourceType": "Encounter", "id": "encounter-1"}))
    encounter = {"resourceType": "Encounter", "identifier": [{"system": "https://example.org/run", "value": "batch-1:patient-1"}]}

    created = HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=1).upsert_resource(encounter)

    expect.equal(created.resource_id, "encounter-1")
    expect.equal(route.calls.last.request.url.params["identifier"], "https://example.org/run|batch-1:patient-1")


SCENARIO_SYSTEM = "https://example.org/fhir/CodeSystem/vitals-simulator-scenario"


@respx.mock
def test_upsert_resource_removes_tags_the_update_no_longer_carries():
    # HAPI keeps an existing resource's tags on update, so a changed scenario would leave both scenario tags.
    tagged = {
        "resourceType": "Encounter",
        "id": "encounter-1",
        "meta": {"tag": [{"system": SCENARIO_SYSTEM, "code": "normal"}, {"system": SCENARIO_SYSTEM, "code": "deterioration_proxy"}]},
    }
    respx.put(f"{FHIR_BASE_URL}/Encounter").mock(return_value=httpx.Response(200, json=tagged))
    meta_delete = respx.post(f"{FHIR_BASE_URL}/Encounter/encounter-1/$meta-delete").mock(return_value=httpx.Response(200, json={"resourceType": "Parameters"}))
    encounter = {
        "resourceType": "Encounter",
        "identifier": [{"system": "https://example.org/run", "value": "batch-1:patient-1"}],
        "meta": {"tag": [{"system": SCENARIO_SYSTEM, "code": "deterioration_proxy"}]},
    }

    HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=1).upsert_resource(encounter)

    removed = json.loads(meta_delete.calls.last.request.content)["parameter"][0]["valueMeta"]["tag"]
    expect.equal(removed, [{"system": SCENARIO_SYSTEM, "code": "normal"}])


@respx.mock
def test_upsert_resource_leaves_matching_tags_alone():
    tagged = {"resourceType": "Encounter", "id": "encounter-1", "meta": {"tag": [{"system": SCENARIO_SYSTEM, "code": "normal"}]}}
    respx.put(f"{FHIR_BASE_URL}/Encounter").mock(return_value=httpx.Response(200, json=tagged))
    meta_delete = respx.post(f"{FHIR_BASE_URL}/Encounter/encounter-1/$meta-delete")
    encounter = {
        "resourceType": "Encounter",
        "identifier": [{"system": "https://example.org/run", "value": "b:p"}],
        "meta": {"tag": [{"system": SCENARIO_SYSTEM, "code": "normal"}]},
    }

    HAPIFHIRClient(base_url=FHIR_BASE_URL, max_retries=1).upsert_resource(encounter)

    expect.equal(meta_delete.call_count, 0)


def test_upsert_resource_requires_an_identifier():
    with pytest.raises(ValueError, match="identifier"):
        HAPIFHIRClient(base_url=FHIR_BASE_URL).upsert_resource({"resourceType": "Encounter"})
