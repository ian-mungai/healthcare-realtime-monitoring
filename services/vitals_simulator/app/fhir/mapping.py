import json
import os
from dataclasses import dataclass
from pathlib import Path

import boto3

DEFAULT_RESOURCE_MAP_FILE = Path(__file__).resolve().parents[4] / "scripts" / "synthea_loader" / "state" / "fhir_resource_map.json"
RESOURCE_MAP_FILE_ENV = "FHIR_RESOURCE_MAP_FILE"
RESOURCE_MAP_S3_BUCKET_ENV = "FHIR_RESOURCE_MAP_S3_BUCKET"
RESOURCE_MAP_S3_KEY_ENV = "FHIR_RESOURCE_MAP_S3_KEY"


@dataclass(frozen=True)
class FHIRPatientContext:
    synthea_patient_id: str
    hapi_patient_id: str
    synthea_encounter_id: str
    hapi_encounter_id: str


def get_resource_map_file() -> Path:
    configured_path = os.getenv(RESOURCE_MAP_FILE_ENV)
    if configured_path:
        return Path(configured_path)
    return DEFAULT_RESOURCE_MAP_FILE


def load_local_fhir_resource_map() -> dict:
    resource_map_file = get_resource_map_file()
    if not resource_map_file.exists():
        raise FileNotFoundError(f"FHIR resource mapping not found: {resource_map_file}")
    with resource_map_file.open(encoding="utf-8") as file:
        return json.load(file)


def load_s3_fhir_resource_map(bucket: str, key: str) -> dict:
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read().decode("utf-8"))


def validate_fhir_resource_map(mapping: dict) -> dict:
    if "patients" not in mapping:
        raise ValueError("FHIR resource map does not contain patients")
    if "encounters" not in mapping:
        raise ValueError("FHIR resource map does not contain encounters")
    return mapping


def load_fhir_resource_map() -> dict:
    """
    Load the Synthea -> HAPI resource mapping.

    Cloud deployments can load the mapping from S3 using:
        FHIR_RESOURCE_MAP_S3_BUCKET
        FHIR_RESOURCE_MAP_S3_KEY

    Local development continues to use:
        FHIR_RESOURCE_MAP_FILE
    """
    bucket = os.getenv(RESOURCE_MAP_S3_BUCKET_ENV)
    key = os.getenv(RESOURCE_MAP_S3_KEY_ENV)
    if bucket or key:
        if not bucket or not key:
            raise RuntimeError(f"{RESOURCE_MAP_S3_BUCKET_ENV} and {RESOURCE_MAP_S3_KEY_ENV} must both be configured")
        return validate_fhir_resource_map(load_s3_fhir_resource_map(bucket, key))
    return validate_fhir_resource_map(load_local_fhir_resource_map())


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
