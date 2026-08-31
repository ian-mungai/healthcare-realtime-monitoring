#!/usr/bin/env bash

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ECS_CLUSTER_NAME="healthcare-realtime-services"
TASK_FAMILY="healthcare_realtime_vitals_simulator"
SECURITY_GROUP_NAME="healthcare-realtime-vitals-simulator"
PROJECT_TAG="healthcare_realtime_monitoring"

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

VPC_ID="$(
  aws ec2 describe-vpcs \
    --region "$AWS_REGION" \
    --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
    --query 'Vpcs[0].VpcId' \
    --output text
)"

if [[ -z "$VPC_ID" || "$VPC_ID" == "None" ]]; then
  echo "Unable to locate the healthcare realtime VPC."
  exit 1
fi

PRIVATE_SUBNETS="$(
  aws ec2 describe-subnets \
    --region "$AWS_REGION" \
    --filters \
      "Name=vpc-id,Values=${VPC_ID}" \
      "Name=map-public-ip-on-launch,Values=false" \
    --query 'Subnets[].SubnetId' \
    --output text
)"

if [[ -z "$PRIVATE_SUBNETS" ]]; then
  echo "Unable to locate the private subnets."
  exit 1
fi

SUBNET_CSV="$(echo "$PRIVATE_SUBNETS" | tr '\t' ',')"

SECURITY_GROUP_ID="$(
  aws ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --filters \
      "Name=vpc-id,Values=${VPC_ID}" \
      "Name=group-name,Values=${SECURITY_GROUP_NAME}" \
    --query 'SecurityGroups[0].GroupId' \
    --output text
)"

if [[ -z "$SECURITY_GROUP_ID" || "$SECURITY_GROUP_ID" == "None" ]]; then
  echo "Unable to locate the vitals simulator security group."
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
