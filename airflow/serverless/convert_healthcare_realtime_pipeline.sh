#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

DBT_TASK_DEFINITION="$(terraform -chdir=infra output -raw dbt_ecs_task_definition_arn)"
DBT_SECURITY_GROUP="$(terraform -chdir=infra output -raw dbt_ecs_security_group_id)"
SODA_TASK_DEFINITION="$(terraform -chdir=infra output -raw soda_ecs_task_definition_arn)"
SODA_SECURITY_GROUP="$(terraform -chdir=infra output -raw soda_ecs_security_group_id)"
DATA_JOBS_CLUSTER="$(terraform -chdir=infra output -raw dbt_ecs_cluster_name)"

PRIVATE_SUBNET_A="$(terraform -chdir=infra state show -no-color module.network.aws_subnet.private_a | awk -F' = ' '/^[[:space:]]*id[[:space:]]*=/{gsub(/"/, "", $2); print $2; exit}')"
PRIVATE_SUBNET_B="$(terraform -chdir=infra state show -no-color module.network.aws_subnet.private_b | awk -F' = ' '/^[[:space:]]*id[[:space:]]*=/{gsub(/"/, "", $2); print $2; exit}')"

export AIRFLOW_ENABLE_TASK_CALLBACKS=false
export AIRFLOW__DBT__ECS_SECURITY_GROUP="$DBT_SECURITY_GROUP"
export AIRFLOW__DBT__ECS_SUBNETS="$PRIVATE_SUBNET_A,$PRIVATE_SUBNET_B"
export AIRFLOW__SODA__ECS_SECURITY_GROUP="$SODA_SECURITY_GROUP"
export AIRFLOW__SODA__ECS_SUBNETS="$PRIVATE_SUBNET_A,$PRIVATE_SUBNET_B"
export DBT_ECS_TASK_DEFINITION="$DBT_TASK_DEFINITION"
export SODA_ECS_TASK_DEFINITION="$SODA_TASK_DEFINITION"
export DATA_JOBS_ECS_CLUSTER="$DATA_JOBS_CLUSTER"

PYTHONPATH="$REPO_ROOT/airflow/dags:$REPO_ROOT" \
python3 airflow/serverless/generate_healthcare_realtime_pipeline.py