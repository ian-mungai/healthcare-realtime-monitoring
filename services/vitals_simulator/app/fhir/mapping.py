import json
from dataclasses import dataclass
from pathlib import Path

RESOURCE_MAP_FILE = Path(__file__).resolve().parents[4] / "scripts" / "synthea_loader" / "state" / "fhir_resource_map.json"


@dataclass(frozen=True)
class FHIRPatientContext:
    synthea_patient_id: str
    hapi_patient_id: str
    synthea_encounter_id: str
    hapi_encounter_id: str


def load_fhir_resource_map() -> dict:
    """
    Load the Synthea -> HAPI resource mapping created
    by the Synthea loader.
    """
    if not RESOURCE_MAP_FILE.exists():
        raise FileNotFoundError(f"FHIR resource mapping not found: {RESOURCE_MAP_FILE}")

    with RESOURCE_MAP_FILE.open(encoding="utf-8") as file:
        mapping = json.load(file)

    if "patients" not in mapping:
        raise ValueError("FHIR resource map does not contain patients")

    if "encounters" not in mapping:
        raise ValueError("FHIR resource map does not contain encounters")

    return mapping


def get_patient_cohort(expected_count: int = 10) -> list[FHIRPatientContext]:
    """
    Return the final Synthea/HAPI patient cohort.

    Every patient must have an explicit matching encounter.
    """
    mapping = load_fhir_resource_map()

    cohort = mapping.get("cohort")

    if not cohort:
        raise RuntimeError("FHIR resource map does not contain cohort mappings. Re-run the Synthea loader.")

    if len(cohort) != expected_count:
        raise RuntimeError(f"Expected {expected_count} cohort patients but found {len(cohort)}")

    contexts = []

    for synthea_patient_id in sorted(cohort):
        entry = cohort[synthea_patient_id]

        contexts.append(
            FHIRPatientContext(
                synthea_patient_id=synthea_patient_id,
                hapi_patient_id=entry["hapi_patient_id"],
                synthea_encounter_id=entry["synthea_encounter_id"],
                hapi_encounter_id=entry["hapi_encounter_id"],
            )
        )

    return contexts


def get_first_patient_and_encounter() -> tuple[str, str]:
    """
    Preserve the original single-patient simulator interface.
    """
    context = get_patient_cohort()[0]

    return context.hapi_patient_id, context.hapi_encounter_id
