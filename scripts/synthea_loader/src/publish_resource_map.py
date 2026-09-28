from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3

from scripts.synthea_loader.src.cohort import cohort_patient_ids
from tools.process import run_command

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = Path(os.getenv("PROJECT_ENV_FILE") or REPO_ROOT / ".env")
DEFAULT_RESOURCE_MAP_FILE = Path(os.getenv("FHIR_RESOURCE_MAP_FILE") or REPO_ROOT / "scripts" / "synthea_loader" / "state" / "fhir_resource_map.json")


def load_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value.strip().strip("\"'")
    return values


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
    run_command(
        str(REPO_ROOT / "scripts" / "infrastructure" / "render_project_config.sh"),
        ["--env-file", str(arguments.env_file), "--resource-map", str(arguments.resource_map)],
        check=True,
        capture=False,
    )
    sys.stdout.write(f"Published the FHIR resource map and rendered {len(patient_ids)} generated patient IDs.\n")


if __name__ == "__main__":
    main()
