#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"
AWS_REGION="${AWS_REGION:?Set AWS_REGION for the target environment.}"
ECS_CLUSTER_NAME="$(terraform -chdir="$REPO_ROOT/infra" output -raw hapi_ecs_cluster_name)"
TASK_FAMILY="$(terraform -chdir="$REPO_ROOT/infra" output -raw vitals_simulator_task_definition_family)"
SECURITY_GROUP_ID="$(terraform -chdir="$REPO_ROOT/infra" output -raw vitals_simulator_security_group_id)"
SUBNET_CSV="$(terraform -chdir="$REPO_ROOT/infra" output -json private_subnet_ids | jq -r 'join(",")')"

echo "Checking for an existing vitals simulator demo task..."

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

if [[ -n "$RUNNING_TASKS" || -n "$PENDING_TASKS" ]]; then
  echo "A vitals simulator demo task is already running or starting."
  exit 1
fi

if [[ -z "$SECURITY_GROUP_ID" || "$SECURITY_GROUP_ID" == "None" ]]; then
  echo "Unable to locate the vitals simulator security group."
  exit 1
fi

if [[ -z "$SUBNET_CSV" ]]; then
  echo "Unable to read private subnets from Terraform outputs."
  exit 1
fi

echo "Starting vitals simulator demo task..."

TASK_ARN="$(
  aws ecs run-task \
    --cluster "$ECS_CLUSTER_NAME" \
    --task-definition "$TASK_FAMILY" \
    --launch-type FARGATE \
    --platform-version LATEST \
    --count 1 \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_CSV}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=DISABLED}" \
    --started-by healthcare-realtime-portfolio-demo \
    --region "$AWS_REGION" \
    --query 'tasks[0].taskArn' \
    --output text
)"

if [[ -z "$TASK_ARN" || "$TASK_ARN" == "None" ]]; then
  echo "ECS did not return a task ARN."
  exit 1
fi

echo "Demo task submitted:"
echo "$TASK_ARN"

echo
echo "Current task state:"

aws ecs describe-tasks \
  --cluster "$ECS_CLUSTER_NAME" \
  --tasks "$TASK_ARN" \
  --region "$AWS_REGION" \
  --query 'tasks[0].{LastStatus:lastStatus,DesiredStatus:desiredStatus,TaskDefinition:taskDefinitionArn,StartedBy:startedBy}'
