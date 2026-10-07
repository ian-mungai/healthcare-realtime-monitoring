"""Run dbt against the local Postgres warehouse with the local settings.

Usage: python -m jobs.local_warehouse.dbt <dbt arguments>, for example ``build`` or ``test --select ml_training_dataset``

The models read the same environment variables on AWS and locally. This runner sets the local values: the warehouse
database and the raw schema the local loader writes, the analytics schema dbt builds, the table names and the cohort's
patient IDs from the local resource map. It turns on the models that read the cohort reference tables. It reads the
warehouse password from deploy/local/.env and runs dbt from the isolated .tools/dbt-postgres environment
(python -m tools.install_tools).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts.infrastructure.render_project_config import load_environment_file
from scripts.synthea_loader.src.cohort import cohort_patient_ids
from tools.process import run_command

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT = REPO_ROOT / ".tools" / "dbt-postgres" / "bin" / "dbt"
STACK_ENV_FILE = REPO_ROOT / "deploy" / "local" / ".env"
DEFAULT_MAP = REPO_ROOT / "build" / "local" / "fhir_resource_map.json"
# The models and sources name their schemas and tables through these variables; the Athena values come from Terraform.
LOCAL_SETTINGS = {
    "ATHENA_CATALOG": "warehouse",
    "ATHENA_SOURCE_DATABASE": "raw",
    "ATHENA_PROCESSED_TABLE": "processed_fhir_observations",
    "ATHENA_DBT_DATABASE": "analytics",
    "ATHENA_ML_DATABASE": "ml",
    "ATHENA_PREDICTIONS_PUBLISHED_TABLE": "ml_predictions_published",
    "DBT_STAGING_TABLE": "stg_fhir_observations",
    "DBT_DIM_DATE_TABLE": "dim_date",
    "DBT_DIM_ENCOUNTER_TABLE": "dim_encounter",
    "DBT_DIM_OBSERVATION_TYPE_TABLE": "dim_observation_type",
    "DBT_DIM_PATIENT_TABLE": "dim_patient",
    "DBT_DIM_PROVIDER_TABLE": "dim_provider",
    "DBT_ENCOUNTER_FEATURES_TABLE": "fact_encounter_vital_features",
    "DBT_FACT_OBSERVATIONS_TABLE": "fact_observations",
    "DBT_ML_TRAINING_TABLE": "ml_training_dataset",
    "DBT_ML_SCORING_TABLE": "ml_scoring_dataset",
    "DBT_ML_PREDICTIONS_SERVING_TABLE": "ml_predictions_serving",
    "DBT_ML_PREDICTIONS_LATEST_TABLE": "ml_predictions_latest",
    "AWS_REGION": "local",
    "DATA_BUCKET_NAME": "local",
}
# The local warehouse holds the cohort reference tables, so the models that read them are on.
LOCAL_VARS = "{cohort_reference_enabled: true}"


def local_environment() -> dict[str, str]:
    if not STACK_ENV_FILE.is_file():
        raise SystemExit("deploy/local/.env is missing; run scripts/local/local_stack.sh start first")
    stack = load_environment_file(STACK_ENV_FILE)
    map_file = Path(os.getenv("FHIR_RESOURCE_MAP_FILE") or DEFAULT_MAP)
    patient_ids = cohort_patient_ids(map_file)
    environment = {**os.environ, **LOCAL_SETTINGS}
    environment["LOCAL_WAREHOUSE_DB_PASSWORD"] = stack["LOCAL_WAREHOUSE_DB_PASSWORD"]
    environment["LOCAL_POSTGRES_PORT"] = stack.get("LOCAL_POSTGRES_PORT", "5432")
    environment["ACTIVE_PATIENT_IDS"] = ",".join(patient_ids)
    return environment


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv) or ["build"]
    if not DBT.is_file():
        raise SystemExit("dbt-postgres is not installed; run .venv/bin/python -m tools.install_tools")
    result = run_command(
        str(DBT),
        [*arguments, "--vars", LOCAL_VARS, "--target", "local", "--profiles-dir", str(REPO_ROOT / "deploy" / "dbt"), "--project-dir", str(REPO_ROOT / "dbt")],
        cwd=REPO_ROOT,
        env=local_environment(),
        timeout=3600,
        capture=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
