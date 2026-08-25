import json
from pathlib import Path

RESOURCE_MAP_FILE = Path(__file__).resolve().parents[4] / "scripts" / "synthea_loader" / "state" / "fhir_resource_map.json"


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


def get_first_patient_and_encounter() -> tuple[str, str]:
    """
    Return one HAPI Patient ID and one HAPI Encounter ID.

    This is sufficient for the first simulator MVP.
    """
    mapping = load_fhir_resource_map()

    patients = mapping["patients"]
    encounters = mapping["encounters"]

    if not patients:
        raise RuntimeError("FHIR resource map contains no patients")

    if not encounters:
        raise RuntimeError("FHIR resource map contains no encounters")

    patient_id = next(iter(patients.values()))

    encounter_id = next(iter(encounters.values()))

    return patient_id, encounter_id
