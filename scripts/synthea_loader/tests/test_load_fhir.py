import json

import httpx
import pytest
import respx

from scripts.synthea_loader.src.load_fhir import (
    FHIR_BASE_URL,
    SYNTHEA_IDENTIFIER_SYSTEM,
    contains_resource,
    ensure_encounter_exists,
    ensure_patient_exists,
    extract_id_from_location,
    find_conditional_references,
    get_resource,
    get_synthea_identifier,
    sanitize_encounter,
    sanitize_patient,
    search_resource_by_identifier,
    select_seed_resources,
)


@pytest.fixture
def sample_patient():
    return {
        "resourceType": "Patient",
        "id": "synthea-patient-1",
        "identifier": [{"system": SYNTHEA_IDENTIFIER_SYSTEM, "value": "synthea-patient-1"}],
        "managingOrganization": {"reference": "Organization?identifier=test"},
        "generalPractitioner": [{"reference": ("Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|123")}],
    }


@pytest.fixture
def older_encounter():
    return {
        "resourceType": "Encounter",
        "id": "synthea-encounter-old",
        "identifier": [{"system": SYNTHEA_IDENTIFIER_SYSTEM, "value": "synthea-encounter-old"}],
        "subject": {"reference": "urn:uuid:patient-full-url"},
        "period": {"start": "2026-08-18T10:00:00Z"},
    }


@pytest.fixture
def sample_encounter():
    return {
        "resourceType": "Encounter",
        "id": "synthea-encounter-1",
        "identifier": [{"system": SYNTHEA_IDENTIFIER_SYSTEM, "value": "synthea-encounter-1"}],
        "subject": {"reference": "urn:uuid:patient-full-url"},
        "period": {"start": "2026-08-20T10:00:00Z"},
        "participant": [{"individual": {"reference": ("Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|123")}}],
        "serviceProvider": {"reference": "Organization?identifier=test"},
        "location": [{"location": {"reference": "Location?identifier=test"}}],
    }


@pytest.fixture
def sample_bundle(sample_patient, older_encounter, sample_encounter):
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"fullUrl": "urn:uuid:patient-full-url", "resource": sample_patient, "request": {"method": "POST", "url": "Patient"}},
            {"fullUrl": "urn:uuid:old-encounter-full-url", "resource": older_encounter, "request": {"method": "POST", "url": "Encounter"}},
            {"fullUrl": "urn:uuid:encounter-full-url", "resource": sample_encounter, "request": {"method": "POST", "url": "Encounter"}},
        ],
    }


def test_contains_resource(sample_bundle):
    assert contains_resource(sample_bundle, "Patient")

    assert contains_resource(sample_bundle, "Encounter")

    assert not contains_resource(sample_bundle, "Observation")


def test_sanitize_patient(sample_patient):
    patient = sanitize_patient(sample_patient)

    assert "managingOrganization" not in patient
    assert "generalPractitioner" not in patient

    assert patient["id"] == "synthea-patient-1"


def test_sanitize_patient_does_not_modify_original(sample_patient):
    sanitize_patient(sample_patient)

    assert "managingOrganization" in sample_patient
    assert "generalPractitioner" in sample_patient


def test_sanitize_encounter(sample_encounter):
    encounter = sanitize_encounter(sample_encounter)

    assert "participant" not in encounter
    assert "serviceProvider" not in encounter
    assert "location" not in encounter

    assert encounter["subject"]["reference"] == ("urn:uuid:patient-full-url")


def test_sanitize_encounter_does_not_modify_original(sample_encounter):
    sanitize_encounter(sample_encounter)

    assert "participant" in sample_encounter
    assert "serviceProvider" in sample_encounter
    assert "location" in sample_encounter


def test_select_seed_resources_chooses_patient_and_latest_encounter(sample_bundle):
    patient, encounter = select_seed_resources(sample_bundle)

    assert patient["resourceType"] == "Patient"
    assert patient["id"] == "synthea-patient-1"

    assert encounter["resourceType"] == "Encounter"
    assert encounter["id"] == "synthea-encounter-1"


def test_select_seed_resources_sanitizes_patient(sample_bundle):
    patient, _ = select_seed_resources(sample_bundle)

    assert "managingOrganization" not in patient
    assert "generalPractitioner" not in patient


def test_select_seed_resources_sanitizes_encounter(sample_bundle):
    _, encounter = select_seed_resources(sample_bundle)

    assert "participant" not in encounter
    assert "serviceProvider" not in encounter
    assert "location" not in encounter


def test_select_seed_resources_requires_patient():
    bundle = {
        "resourceType": "Bundle",
        "entry": [{"resource": {"resourceType": "Encounter", "id": "encounter-1", "period": {"start": "2026-08-20T10:00:00Z"}}}],
    }

    with pytest.raises(RuntimeError, match="No Patient resource found"):
        select_seed_resources(bundle)


def test_select_seed_resources_requires_encounter():
    bundle = {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Patient", "id": "patient-1"}}]}

    with pytest.raises(RuntimeError, match="No Encounter resources found"):
        select_seed_resources(bundle)


def test_find_conditional_references(sample_encounter):
    references = find_conditional_references(sample_encounter)

    assert "Practitioner?identifier=http://hl7.org/fhir/sid/us-npi|123" in references

    assert "Organization?identifier=test" in references

    assert "Location?identifier=test" in references


def test_sanitized_encounter_has_no_conditional_references(sample_encounter):
    encounter = sanitize_encounter(sample_encounter)

    references = find_conditional_references(encounter)

    assert references == set()


def test_get_synthea_identifier(sample_patient):
    system, value = get_synthea_identifier(sample_patient)

    assert system == SYNTHEA_IDENTIFIER_SYSTEM
    assert value == "synthea-patient-1"


def test_get_synthea_identifier_fallback():
    resource = {"resourceType": "Patient", "identifier": [{"system": "https://example.org/test", "value": "abc123"}]}

    system, value = get_synthea_identifier(resource)

    assert system == "https://example.org/test"
    assert value == "abc123"


def test_get_synthea_identifier_missing():
    resource = {"resourceType": "Patient", "identifier": []}

    with pytest.raises(RuntimeError, match="does not contain a usable identifier"):
        get_synthea_identifier(resource)


def test_extract_id_from_relative_location():
    resource_id = extract_id_from_location("Patient/137506799/_history/1")

    assert resource_id == "137506799"


def test_extract_id_from_absolute_location():
    resource_id = extract_id_from_location("https://hapi.fhir.org/baseR4/Patient/137506799/_history/1")

    assert resource_id == "137506799"


@respx.mock
def test_search_resource_by_identifier_found():
    route = respx.get(f"{FHIR_BASE_URL}/Patient").mock(
        return_value=httpx.Response(
            200, json={"resourceType": "Bundle", "type": "searchset", "total": 1, "entry": [{"resource": {"resourceType": "Patient", "id": "137506799"}}]}
        )
    )

    resource = search_resource_by_identifier("Patient", SYNTHEA_IDENTIFIER_SYSTEM, "synthea-patient-1")

    assert route.called
    assert resource is not None
    assert resource["resourceType"] == "Patient"
    assert resource["id"] == "137506799"


@respx.mock
def test_search_resource_by_identifier_not_found():
    route = respx.get(f"{FHIR_BASE_URL}/Patient").mock(return_value=httpx.Response(200, json={"resourceType": "Bundle", "type": "searchset", "total": 0}))

    resource = search_resource_by_identifier("Patient", SYNTHEA_IDENTIFIER_SYSTEM, "missing-patient")

    assert route.called
    assert resource is None


@respx.mock
def test_get_resource():
    route = respx.get(f"{FHIR_BASE_URL}/Patient/137506799").mock(return_value=httpx.Response(200, json={"resourceType": "Patient", "id": "137506799"}))

    patient = get_resource("Patient", "137506799")

    assert route.called
    assert patient["resourceType"] == "Patient"
    assert patient["id"] == "137506799"


@respx.mock
def test_ensure_patient_exists_reuses_existing(sample_patient):
    search_route = respx.get(f"{FHIR_BASE_URL}/Patient").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "searchset",
                "total": 1,
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "137506799",
                            "identifier": [{"system": (SYNTHEA_IDENTIFIER_SYSTEM), "value": ("synthea-patient-1")}],
                        }
                    }
                ],
            },
        )
    )

    patient = sanitize_patient(sample_patient)

    result = ensure_patient_exists(patient)

    assert search_route.called
    assert result["id"] == "137506799"


@respx.mock
def test_ensure_patient_exists_creates_when_missing(sample_patient):
    search_route = respx.get(f"{FHIR_BASE_URL}/Patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle", "type": "searchset", "total": 0})
    )

    create_route = respx.post(f"{FHIR_BASE_URL}/Patient").mock(return_value=httpx.Response(201, json={"resourceType": "Patient", "id": "new-patient-id"}))

    patient = sanitize_patient(sample_patient)

    result = ensure_patient_exists(patient)

    assert search_route.called
    assert create_route.called

    assert result["resourceType"] == "Patient"
    assert result["id"] == "new-patient-id"


@respx.mock
def test_ensure_encounter_exists_reuses_existing(sample_encounter):
    search_route = respx.get(f"{FHIR_BASE_URL}/Encounter").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "type": "searchset",
                "total": 1,
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Encounter",
                            "id": "137506800",
                            "identifier": [{"system": (SYNTHEA_IDENTIFIER_SYSTEM), "value": ("synthea-encounter-1")}],
                        }
                    }
                ],
            },
        )
    )

    encounter = sanitize_encounter(sample_encounter)

    result = ensure_encounter_exists(encounter, "137506799")

    assert search_route.called
    assert result["id"] == "137506800"


@respx.mock
def test_ensure_encounter_exists_creates_when_missing(sample_encounter):
    search_route = respx.get(f"{FHIR_BASE_URL}/Encounter").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle", "type": "searchset", "total": 0})
    )

    create_route = respx.post(f"{FHIR_BASE_URL}/Encounter").mock(
        return_value=httpx.Response(201, json={"resourceType": "Encounter", "id": "new-encounter-id", "subject": {"reference": "Patient/137506799"}})
    )

    encounter = sanitize_encounter(sample_encounter)

    result = ensure_encounter_exists(encounter, "137506799")

    assert search_route.called
    assert create_route.called

    assert result["resourceType"] == "Encounter"
    assert result["id"] == "new-encounter-id"

    request = create_route.calls[0].request

    submitted = json.loads(request.content.decode("utf-8"))

    assert submitted["subject"]["reference"] == ("Patient/137506799")
