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
