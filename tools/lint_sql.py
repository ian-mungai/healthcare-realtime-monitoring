"""Lint the dbt SQL with SQLFluff and its dbt templater, using placeholder deployment names.

Usage: python -m tools.lint_sql [--fix] [file ...]   (every model and singular test when no file is given)

The templater compiles each model with dbt, which reads deployment names through ``env_var``. This runner supplies
fixed placeholders so the result never depends on a local ``.env`` and no real value reaches the compiled SQL. Nothing
connects to AWS. Rules and the Athena dialect are in ``.sqlfluff``; see docs/quality-checks.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from tools.process import run_command

ROOT = Path(__file__).resolve().parents[1]
SQLFLUFF = ROOT / ".tools" / "bin" / "sqlfluff"
DEFAULT_PATHS = ("dbt/models", "dbt/tests")

MODEL_TABLES = {
    "DBT_STAGING_TABLE": "stg_fhir_observations",
    "DBT_DIM_PATIENT_TABLE": "dim_patient",
    "DBT_DIM_ENCOUNTER_TABLE": "dim_encounter",
    "DBT_DIM_PROVIDER_TABLE": "dim_provider",
    "DBT_DIM_OBSERVATION_TYPE_TABLE": "dim_observation_type",
    "DBT_DIM_DATE_TABLE": "dim_date",
    "DBT_FACT_OBSERVATIONS_TABLE": "fact_observations",
    "DBT_ENCOUNTER_FEATURES_TABLE": "fact_encounter_vital_features",
    "DBT_ML_TRAINING_TABLE": "ml_training_dataset",
    "DBT_ML_SCORING_TABLE": "ml_scoring_dataset",
    "DBT_ML_PREDICTIONS_SERVING_TABLE": "ml_predictions_serving",
    "DBT_ML_PREDICTIONS_LATEST_TABLE": "ml_predictions_latest",
}
PLACEHOLDERS = {
    **MODEL_TABLES,
    "ATHENA_CATALOG": "awsdatacatalog",
    "ATHENA_DBT_DATABASE": "lint_dbt",
    "ATHENA_SOURCE_DATABASE": "lint_source",
    "ATHENA_ML_DATABASE": "lint_ml",
    "ATHENA_PROCESSED_TABLE": "processed_fhir_observations",
    "ATHENA_PREDICTIONS_PUBLISHED_TABLE": "ml_predictions_published",
    "ACTIVE_PATIENT_IDS": ",".join(f"patient-{number:02d}" for number in range(1, 11)),
    "ML_APPROVED_MODEL_VERSION": "lint-model-version",
    "AWS_REGION": "us-east-1",
    "DATA_BUCKET_NAME": "lint-placeholder-bucket",
    "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
}


def main(argv: list[str] | None = None) -> int:
    """Run SQLFluff over the given SQL files, or over every model and singular test."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--fix", action="store_true", help="apply SQLFluff's fixes instead of only reporting")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    if not SQLFLUFF.exists():
        sys.stderr.write("SQLFluff is not installed; run .venv/bin/python -m tools.install_tools\n")
        return 1
    paths = args.paths or [path for path in DEFAULT_PATHS if (ROOT / path).exists()]
    command = ["fix", "--show-lint-violations"] if args.fix else ["lint"]
    result = run_command(str(SQLFLUFF), [*command, *paths], cwd=ROOT, timeout=900, env={**os.environ, **PLACEHOLDERS}, capture=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
