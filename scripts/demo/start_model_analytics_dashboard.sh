#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"

: "${AWS_REGION:?Set AWS_REGION in the project environment file.}"
"$REPO_ROOT/scripts/infrastructure/render_project_config.sh" >/dev/null
TFVARS_FILE="${TFVARS_FILE:-$REPO_ROOT/infra/deployment.auto.tfvars.json}"

MODEL_CONFIG="$({
  printf '%s\n' \
    'jsonencode({catalog=var.athena_catalog_name,workgroup=var.athena_workgroup_name,database=var.dbt_database_name,predictions=var.dbt_ml_predictions_latest_table_name,patients=var.dbt_dim_patient_table_name,encounters=var.dbt_dim_encounter_table_name,features=var.dbt_encounter_features_table_name,results=var.athena_results_s3_uri})'
} | terraform -chdir="$REPO_ROOT/infra" console -var-file="$TFVARS_FILE" | jq -r '.')"

export ATHENA_CATALOG="$(jq -r '.catalog' <<<"$MODEL_CONFIG")"
export ATHENA_WORKGROUP="$(jq -r '.workgroup' <<<"$MODEL_CONFIG")"
export ATHENA_DBT_DATABASE="$(jq -r '.database' <<<"$MODEL_CONFIG")"
export DBT_ML_PREDICTIONS_LATEST_TABLE="$(jq -r '.predictions' <<<"$MODEL_CONFIG")"
export DBT_DIM_PATIENT_TABLE="$(jq -r '.patients' <<<"$MODEL_CONFIG")"
export DBT_DIM_ENCOUNTER_TABLE="$(jq -r '.encounters' <<<"$MODEL_CONFIG")"
export DBT_ENCOUNTER_FEATURES_TABLE="$(jq -r '.features' <<<"$MODEL_CONFIG")"
export ATHENA_RESULTS_S3_URI="$(jq -r '.results' <<<"$MODEL_CONFIG")"

cd "$REPO_ROOT"
exec env PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" -m streamlit run dashboard/model_analytics_app.py \
  --server.port "${MODEL_ANALYTICS_DASHBOARD_PORT:-8502}"
