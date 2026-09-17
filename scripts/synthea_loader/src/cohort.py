from __future__ import annotations

import json
from pathlib import Path

COHORT_SIZE = 10


def cohort_patient_ids(resource_map_path: Path) -> tuple[str, ...]:
    resource_map = json.loads(resource_map_path.read_text(encoding="utf-8"))
    cohort = resource_map.get("cohort")
    if not isinstance(cohort, dict) or len(cohort) != COHORT_SIZE:
        raise ValueError(f"FHIR resource map must contain exactly {COHORT_SIZE} cohort entries")

    patient_ids = tuple(str(entry.get("hapi_patient_id", "")).strip() for entry in cohort.values() if isinstance(entry, dict))
    if len(patient_ids) != COHORT_SIZE or any(not patient_id for patient_id in patient_ids):
        raise ValueError("Every cohort entry must contain a HAPI patient ID")
    if len(set(patient_ids)) != COHORT_SIZE:
        raise ValueError("HAPI patient IDs must be unique")

    return tuple(sorted(patient_ids, key=lambda patient_id: (not patient_id.isdigit(), patient_id.zfill(20) if patient_id.isdigit() else patient_id)))
