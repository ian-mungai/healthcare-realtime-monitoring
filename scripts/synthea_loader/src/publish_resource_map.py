from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_RESOURCE_MAP_FILE = REPO_ROOT / "scripts" / "synthea_loader" / "state" / "fhir_resource_map.json"
COHORT_SIZE = 10


def load_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value.strip().strip("\"'")
    return values


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


def update_patient_ids(environment_path: Path, patient_ids: tuple[str, ...]) -> None:
    lines = environment_path.read_text(encoding="utf-8").splitlines()
    assignment = f"PATIENT_IDS={','.join(patient_ids)}"
    matches = [index for index, line in enumerate(lines) if line.startswith("PATIENT_IDS=")]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one PATIENT_IDS assignment in {environment_path}")
    lines[matches[0]] = assignment
    environment_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish_resource_map(environment: dict[str, str], resource_map_path: Path) -> None:
    required = ("AWS_PROFILE", "AWS_REGION", "DATA_BUCKET_NAME", "FHIR_RESOURCE_MAP_S3_KEY")
    missing = [name for name in required if not environment.get(name)]
    if missing:
        raise ValueError(f"Missing required environment values: {', '.join(missing)}")

    session = boto3.Session(profile_name=environment["AWS_PROFILE"], region_name=environment["AWS_REGION"])
    session.client("s3").upload_file(str(resource_map_path), environment["DATA_BUCKET_NAME"], environment["FHIR_RESOURCE_MAP_S3_KEY"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the generated FHIR map and synchronize the deployed patient cohort.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--resource-map", type=Path, default=DEFAULT_RESOURCE_MAP_FILE)
    arguments = parser.parse_args()

    patient_ids = cohort_patient_ids(arguments.resource_map)
    environment = load_environment(arguments.env_file)
    publish_resource_map(environment, arguments.resource_map)
    update_patient_ids(arguments.env_file, patient_ids)
    subprocess.run([str(REPO_ROOT / "scripts" / "infrastructure" / "render_project_config.sh")], check=True)
    print(f"Published the FHIR resource map and synchronized {len(patient_ids)} patient IDs.")


if __name__ == "__main__":
    main()
