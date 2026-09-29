from services.vitals_simulator.app.fhir.identifier import SIMULATOR_IDENTIFIER_SYSTEM, add_observation_identifier, build_observation_identifier
from testkit import expect

EFFECTIVE_DATETIME = "2026-08-31T16:55:47+00:00"
LATER_EFFECTIVE_DATETIME = "2026-08-31T16:55:48+00:00"


def test_identifier_is_deterministic():
    first = build_observation_identifier("patient-001", "bidmc01n", 10, "8867-4", EFFECTIVE_DATETIME)
    second = build_observation_identifier("patient-001", "bidmc01n", 10, "8867-4", EFFECTIVE_DATETIME)
    expect.equal(first, second)


def test_different_offsets_produce_different_identifiers():
    first = build_observation_identifier("patient-001", "bidmc01n", 10, "8867-4", EFFECTIVE_DATETIME)
    second = build_observation_identifier("patient-001", "bidmc01n", 11, "8867-4", EFFECTIVE_DATETIME)
    expect.not_equal(first, second)


def test_different_patients_produce_different_identifiers():
    first = build_observation_identifier("patient-001", "bidmc01n", 10, "8867-4", EFFECTIVE_DATETIME)
    second = build_observation_identifier("patient-002", "bidmc01n", 10, "8867-4", EFFECTIVE_DATETIME)
    expect.not_equal(first, second)


def test_different_effective_datetimes_produce_different_identifiers():
    first = build_observation_identifier("patient-001", "bidmc01n", 10, "8867-4", EFFECTIVE_DATETIME)
    second = build_observation_identifier("patient-001", "bidmc01n", 10, "8867-4", LATER_EFFECTIVE_DATETIME)
    expect.not_equal(first, second)


def test_add_observation_identifier():
    observation = {
        "resourceType": "Observation",
        "subject": {"reference": "Patient/patient-001"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "effectiveDateTime": EFFECTIVE_DATETIME,
    }
    result = add_observation_identifier(observation, "bidmc01n", 10)
    expect.equal(result["identifier"][0]["system"], SIMULATOR_IDENTIFIER_SYSTEM)
    if not result["identifier"][0]["value"]:
        expect.fail('expected: result["identifier"][0]["value"]')


def test_add_observation_identifier_is_patient_specific():
    first_observation = {
        "resourceType": "Observation",
        "subject": {"reference": "Patient/patient-001"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "effectiveDateTime": EFFECTIVE_DATETIME,
    }
    second_observation = {
        "resourceType": "Observation",
        "subject": {"reference": "Patient/patient-002"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "effectiveDateTime": EFFECTIVE_DATETIME,
    }
    first = add_observation_identifier(first_observation, "bidmc01n", 10)
    second = add_observation_identifier(second_observation, "bidmc01n", 10)
    expect.not_equal(first["identifier"][0]["value"], second["identifier"][0]["value"])


def test_add_observation_identifier_requires_effective_datetime():
    observation = {
        "resourceType": "Observation",
        "subject": {"reference": "Patient/patient-001"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
    }
    try:
        add_observation_identifier(observation, "bidmc01n", 10)
    except ValueError as error:
        expect.equal(str(error), "Observation effectiveDateTime is required")
    else:
        raise AssertionError("Expected ValueError")
