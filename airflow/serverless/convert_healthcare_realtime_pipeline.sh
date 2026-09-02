#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${PYTHON_BIN:-}" && -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

DBT_TASK_DEFINITION="$(terraform -chdir=infra output -raw dbt_ecs_task_definition_family)"
DBT_SECURITY_GROUP="$(terraform -chdir=infra output -raw dbt_ecs_security_group_id)"
SODA_TASK_DEFINITION="$(terraform -chdir=infra output -raw soda_ecs_task_definition_family)"
SODA_SECURITY_GROUP="$(terraform -chdir=infra output -raw soda_ecs_security_group_id)"
DATA_JOBS_CLUSTER="$(terraform -chdir=infra output -raw dbt_ecs_cluster_name)"
PRIVATE_SUBNETS="$(terraform -chdir=infra output -json private_subnet_ids | "$PYTHON_BIN" -c 'import json,sys; print(",".join(json.load(sys.stdin)))')"

export AIRFLOW_ENABLE_TASK_CALLBACKS=false
export AIRFLOW__DBT__ECS_SECURITY_GROUP="$DBT_SECURITY_GROUP"
export AIRFLOW__DBT__ECS_SUBNETS="$PRIVATE_SUBNETS"
export AIRFLOW__SODA__ECS_SECURITY_GROUP="$SODA_SECURITY_GROUP"
export AIRFLOW__SODA__ECS_SUBNETS="$PRIVATE_SUBNETS"
export DBT_ECS_TASK_DEFINITION="$DBT_TASK_DEFINITION"
export SODA_ECS_TASK_DEFINITION="$SODA_TASK_DEFINITION"
export DATA_JOBS_ECS_CLUSTER="$DATA_JOBS_CLUSTER"

PYTHONPATH="$REPO_ROOT/airflow/dags:$REPO_ROOT" \
"$PYTHON_BIN" airflow/serverless/generate_healthcare_realtime_pipeline.py
