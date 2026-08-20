from services.vitals_simulator.app.fhir.identifier import SIMULATOR_IDENTIFIER_SYSTEM, add_observation_identifier, build_observation_identifier


def test_identifier_is_deterministic():
    first = build_observation_identifier("bidmc01n", 10, "8867-4")
    second = build_observation_identifier("bidmc01n", 10, "8867-4")

    assert first == second


def test_different_offsets_produce_different_identifiers():
    first = build_observation_identifier("bidmc01n", 10, "8867-4")
    second = build_observation_identifier("bidmc01n", 11, "8867-4")

    assert first != second


def test_add_observation_identifier():
    observation = {
        "resourceType": "Observation",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "8867-4",
                }
            ]
        },
    }

    result = add_observation_identifier(observation, "bidmc01n", 10)

    assert result["identifier"][0]["system"] == SIMULATOR_IDENTIFIER_SYSTEM
    assert result["identifier"][0]["value"]