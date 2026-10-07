from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.vitals_simulator.app.fhir.admission import Admission

SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM = "https://example.org/fhir/identifier/vitals-simulator-encounter"
# Tags the scenario of a run long enough to produce an outcome label, so later runs can balance each patient.
SIMULATOR_SCENARIO_TAG_SYSTEM = "https://example.org/fhir/CodeSystem/vitals-simulator-scenario"
# Marks the batch null control's run identifiers (batch-<seed>-null-<run>), so its encounters stay apart from the study's.
NULL_CONTROL_RUN_MARKER = "-null-"


def is_null_control_run(run_id: str) -> bool:
    return run_id.startswith("batch-") and NULL_CONTROL_RUN_MARKER in run_id


def build_simulator_encounter(
    patient_id: str, run_id: str, started_at: datetime, scenario: str | None = None, admission: Admission | None = None, status: str = "in-progress"
) -> dict:
    """A simulator Encounter. A live run is in progress; the batch writes completed historical stays as finished."""
    if started_at.tzinfo is None:
        raise ValueError("started_at must be timezone-aware")
    encounter = {
        "resourceType": "Encounter",
        "identifier": [{"system": SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, "value": f"{run_id}:{patient_id}"}],
        "status": status,
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": started_at.isoformat()},
    }
    if admission is not None:
        from services.vitals_simulator.app.fhir.admission import admission_fields

        encounter.update(admission_fields(admission, started_at))
    if scenario:
        encounter["meta"] = {"tag": [{"system": SIMULATOR_SCENARIO_TAG_SYSTEM, "code": scenario}]}
    return encounter
