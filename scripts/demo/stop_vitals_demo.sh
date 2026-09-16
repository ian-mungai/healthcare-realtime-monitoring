#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"
AWS_REGION="${AWS_REGION:?Set AWS_REGION for the target environment.}"
ECS_CLUSTER_NAME="$(terraform -chdir="$REPO_ROOT/infra" output -raw hapi_ecs_cluster_name)"
TASK_FAMILY="$(terraform -chdir="$REPO_ROOT/infra" output -raw vitals_simulator_task_definition_family)"

RUNNING_TASKS="$(
  aws ecs list-tasks \
    --cluster "$ECS_CLUSTER_NAME" \
    --family "$TASK_FAMILY" \
    --desired-status RUNNING \
    --region "$AWS_REGION" \
    --query 'taskArns' \
    --output text
)"

PENDING_TASKS="$(
  aws ecs list-tasks \
    --cluster "$ECS_CLUSTER_NAME" \
    --family "$TASK_FAMILY" \
    --desired-status PENDING \
    --region "$AWS_REGION" \
    --query 'taskArns' \
    --output text
)"

TASK_ARNS="$RUNNING_TASKS $PENDING_TASKS"
TASK_ARNS="$(echo "$TASK_ARNS" | xargs)"

if [[ -z "$TASK_ARNS" ]]; then
  echo "Vitals simulator demo is already stopped."
  exit 0
fi

for TASK_ARN in $TASK_ARNS; do
  echo "Stopping $TASK_ARN"

  aws ecs stop-task \
    --cluster "$ECS_CLUSTER_NAME" \
    --task "$TASK_ARN" \
    --reason "Portfolio demo stopped" \
    --region "$AWS_REGION" \
    --query 'task.{TaskArn:taskArn,LastStatus:lastStatus,DesiredStatus:desiredStatus}'
done

echo
echo "Vitals simulator demo stop requested."
