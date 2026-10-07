from __future__ import annotations

import json
import os
from pathlib import Path

# AWS runs the ten-patient demo cohort; local development sets COHORT_SIZE=100. The upper limit
# keeps the cohort within the simulator's waveform reuse and the local stack's tested size.
DEFAULT_COHORT_SIZE = 10
MAX_COHORT_SIZE = 100


def cohort_size() -> int:
    """The configured cohort size from COHORT_SIZE, 10 when unset; stop on a value outside 1 to 100."""
    value = os.getenv("COHORT_SIZE", "").strip()
    if not value:
        return DEFAULT_COHORT_SIZE
    if not value.isdigit() or not 1 <= int(value) <= MAX_COHORT_SIZE:
        raise ValueError(f"COHORT_SIZE must be a whole number from 1 to {MAX_COHORT_SIZE}")
    return int(value)


def cohort_patient_ids(resource_map_path: Path) -> tuple[str, ...]:
    expected = cohort_size()
    resource_map = json.loads(resource_map_path.read_text(encoding="utf-8"))
    cohort = resource_map.get("cohort")
    if not isinstance(cohort, dict) or len(cohort) != expected:
        raise ValueError(f"FHIR resource map must contain exactly {expected} cohort entries")

    patient_ids = tuple(str(entry.get("hapi_patient_id", "")).strip() for entry in cohort.values() if isinstance(entry, dict))
    if len(patient_ids) != expected or any(not patient_id for patient_id in patient_ids):
        raise ValueError("Every cohort entry must contain a HAPI patient ID")
    if len(set(patient_ids)) != expected:
        raise ValueError("HAPI patient IDs must be unique")

    return tuple(sorted(patient_ids, key=lambda patient_id: (not patient_id.isdigit(), patient_id.zfill(20) if patient_id.isdigit() else patient_id)))
