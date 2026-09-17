from datetime import datetime

SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM = "https://example.org/fhir/identifier/vitals-simulator-encounter"


def build_simulator_encounter(patient_id: str, run_id: str, started_at: datetime) -> dict:
    if started_at.tzinfo is None:
        raise ValueError("started_at must be timezone-aware")
    return {
        "resourceType": "Encounter",
        "identifier": [{"system": SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, "value": f"{run_id}:{patient_id}"}],
        "status": "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": started_at.isoformat()},
    }
