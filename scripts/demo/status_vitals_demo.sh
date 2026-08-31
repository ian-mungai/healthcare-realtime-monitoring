#!/usr/bin/env bash

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ECS_CLUSTER_NAME="healthcare-realtime-services"
TASK_FAMILY="healthcare_realtime_vitals_simulator"

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
  echo "Vitals simulator demo is stopped."
  exit 0
fi

aws ecs describe-tasks \
  --cluster "$ECS_CLUSTER_NAME" \
  --tasks $TASK_ARNS \
  --region "$AWS_REGION" \
  --query 'tasks[].{TaskArn:taskArn,Status:lastStatus,DesiredStatus:desiredStatus,StartedAt:startedAt,StartedBy:startedBy,HealthStatus:healthStatus}' \
  --output table
