from datetime import datetime

SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM = "https://example.org/fhir/identifier/vitals-simulator-encounter"
# Tags the scenario of a run long enough to produce an outcome label, so later runs can balance each patient.
SIMULATOR_SCENARIO_TAG_SYSTEM = "https://example.org/fhir/CodeSystem/vitals-simulator-scenario"


def build_simulator_encounter(patient_id: str, run_id: str, started_at: datetime, scenario: str | None = None) -> dict:
    if started_at.tzinfo is None:
        raise ValueError("started_at must be timezone-aware")
    encounter = {
        "resourceType": "Encounter",
        "identifier": [{"system": SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, "value": f"{run_id}:{patient_id}"}],
        "status": "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": started_at.isoformat()},
    }
    if scenario:
        encounter["meta"] = {"tag": [{"system": SIMULATOR_SCENARIO_TAG_SYSTEM, "code": scenario}]}
    return encounter
