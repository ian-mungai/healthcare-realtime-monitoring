#!/usr/bin/env bash
# Run the one-off FHIR setup task inside the project VPC and record the run (docs/fhir-setup-tasks.md).
#   load      upload the generated Synthea bundles, seed the cohort into HAPI, then render the ten patient IDs
#   register  register the webhook subscription after the application stage (reuses an existing one)
# Every run, passed or failed, writes report.json and report.md under artifacts/e2e/fhir_setup/.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
ENV_FILE="${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"
load_project_env "$ENV_FILE"
require_selected_backend "$REPO_ROOT/infra"

COMMAND="${1:-}"
if [[ "$COMMAND" != "load" && "$COMMAND" != "register" ]]; then
  echo "Usage: $0 load|register" >&2
  exit 2
fi

AWS_REGION="${AWS_REGION:?Set AWS_REGION for the target environment.}"
DATA_BUCKET_NAME="${DATA_BUCKET_NAME:?Set DATA_BUCKET_NAME in .env.}"
FHIR_RESOURCE_MAP_S3_KEY="${FHIR_RESOURCE_MAP_S3_KEY:?Set FHIR_RESOURCE_MAP_S3_KEY in .env.}"
RESOURCE_MAP_FILE="${FHIR_RESOURCE_MAP_FILE:-$REPO_ROOT/scripts/synthea_loader/state/fhir_resource_map.json}"
BUNDLE_DIR="$REPO_ROOT/scripts/synthea_loader/synthea/output/fhir"

tf_output() {
  terraform -chdir="$REPO_ROOT/infra" output -raw "$1"
}

ECS_CLUSTER_NAME="$(tf_output hapi_ecs_cluster_name)"
TASK_FAMILY="$(tf_output fhir_setup_task_definition_family)"
SECURITY_GROUP_ID="$(tf_output fhir_setup_security_group_id)"
LOG_GROUP="$(tf_output fhir_setup_log_group_name)"
# The foundation stage is a targeted apply, which does not record outputs that depend on no resource, so the prefix
# is read from the task definition the setup task actually runs with.
SEED_PREFIX="$(aws ecs describe-task-definition --task-definition "$TASK_FAMILY" --region "$AWS_REGION" \
  --query "taskDefinition.containerDefinitions[0].environment[?name=='SEED_BUNDLES_S3_PREFIX'].value | [0]" --output text)"
if [ -z "$SEED_PREFIX" ] || [ "$SEED_PREFIX" = "None" ]; then
  echo "The FHIR setup task definition has no SEED_BUNDLES_S3_PREFIX; apply the foundation stage first." >&2
  exit 2
fi
SUBNET_CSV="$(terraform -chdir="$REPO_ROOT/infra" output -json private_subnet_ids | jq -r 'join(",")')"

RUN_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ARTIFACT_DIR="${FHIR_SETUP_ARTIFACT_DIR:-$REPO_ROOT/artifacts/e2e/fhir_setup}/$(date -u +%Y%m%dT%H%M%SZ)_$COMMAND"
TASK_ARN=""
TASK_ID=""
EXIT_CODE=""
STOPPED_REASON=""
STATUS="failed"
ERROR=""

write_report() {
  mkdir -p "$ARTIFACT_DIR"
  local revision dirty
  revision="$(git -C "$REPO_ROOT" rev-parse HEAD)"
  dirty="$([[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=no)" ]] && echo true || echo false)"
  jq -n \
    --arg run_at "$RUN_AT" --arg command "$COMMAND" --arg revision "$revision" --argjson dirty "$dirty" \
    --arg task_definition_family "$TASK_FAMILY" --arg task_id "$TASK_ID" --arg exit_code "$EXIT_CODE" \
    --arg stopped_reason "$STOPPED_REASON" --arg status "$STATUS" --arg error "$ERROR" --arg log_group "$LOG_GROUP" \
    '{run_at: $run_at, command: $command, code_revision: $revision, uncommitted_tracked_changes: $dirty,
      task_definition_family: $task_definition_family, task_id: $task_id, container_exit_code: $exit_code,
      stopped_reason: $stopped_reason, status: $status, error: $error, log_group: $log_group,
      limits: "Checks the task outcome only; the loaded resources and subscription are verified in HAPI and by the live demo."}' \
    > "$ARTIFACT_DIR/report.json"
  {
    echo "# FHIR setup run: $COMMAND"
    echo
    echo "| Field | Value |"
    echo "| --- | --- |"
    echo "| Run at (UTC) | $RUN_AT |"
    echo "| Status | $STATUS |"
    echo "| Code revision | \`$revision\` (uncommitted tracked changes: $dirty) |"
    echo "| Task definition family | \`$TASK_FAMILY\` |"
    echo "| Task ID | \`${TASK_ID:-not started}\` |"
    echo "| Container exit code | ${EXIT_CODE:-none} |"
    echo "| Stopped reason | ${STOPPED_REASON:-none} |"
    echo "| Error | ${ERROR:-none} |"
    echo "| Logs | CloudWatch \`$LOG_GROUP\` |"
    echo
    echo "Limits: checks the task outcome only; the loaded resources and subscription are verified in HAPI and by the live demo."
  } > "$ARTIFACT_DIR/report.md"
  echo "Report: $ARTIFACT_DIR/report.md"
}

fail() {
  ERROR="$1"
  echo "$1" >&2
  write_report
  exit 1
}

if [[ -n "$(aws ecs list-tasks --cluster "$ECS_CLUSTER_NAME" --family "$TASK_FAMILY" --region "$AWS_REGION" --query 'taskArns' --output text)" ]]; then
  fail "A FHIR setup task is already running; wait for it to stop."
fi

OVERRIDE_ENV="[]"
if [[ "$COMMAND" == "load" ]]; then
  if ! compgen -G "$BUNDLE_DIR/*.json" >/dev/null; then
    fail "No generated Synthea bundles in $BUNDLE_DIR; run scripts/synthea_loader/scripts/generate.sh first."
  fi
  echo "Uploading the generated Synthea bundles..."
  aws s3 sync "$BUNDLE_DIR" "s3://$DATA_BUCKET_NAME/$SEED_PREFIX/" \
    --exclude "*" --include "*.json" --delete --sse AES256 --only-show-errors --region "$AWS_REGION"
else
  WEBHOOK_URL="$(tf_output fhir_webhook_url)"
  if [[ "$WEBHOOK_URL" != https://* ]]; then
    fail "The webhook URL output is missing or not HTTPS; apply the application stage first."
  fi
  OVERRIDE_ENV="$(jq -cn --arg url "$WEBHOOK_URL" '[{name: "FHIR_WEBHOOK_URL", value: $url}]')"
fi

OVERRIDES="$(jq -cn --arg command "$COMMAND" --argjson env "$OVERRIDE_ENV" \
  '{containerOverrides: [{name: "fhir_setup", command: ["python", "-m", "jobs.fhir_setup.task", $command], environment: $env}]}')"

echo "Starting the FHIR setup task ($COMMAND)..."
RUN_RESULT="$(
  aws ecs run-task \
    --cluster "$ECS_CLUSTER_NAME" \
    --task-definition "$TASK_FAMILY" \
    --launch-type FARGATE \
    --platform-version LATEST \
    --count 1 \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_CSV}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=DISABLED}" \
    --overrides "$OVERRIDES" \
    --started-by healthcare-realtime-fhir-setup \
    --region "$AWS_REGION" \
    --output json
)"
TASK_ARN="$(jq -r '.tasks[0].taskArn // empty' <<<"$RUN_RESULT")"
if [[ -z "$TASK_ARN" ]]; then
  fail "ECS did not start the task: $(jq -r '[.failures[]?.reason] | join("; ")' <<<"$RUN_RESULT")"
fi
# Reports keep only the task ID: the full ARN contains the AWS account ID.
TASK_ID="${TASK_ARN##*/}"

echo "Waiting for task $TASK_ID to stop..."
# The tasks-stopped waiter polls every 6 seconds for up to 10 minutes.
if ! aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER_NAME" --tasks "$TASK_ARN" --region "$AWS_REGION"; then
  aws ecs stop-task --cluster "$ECS_CLUSTER_NAME" --task "$TASK_ARN" --reason "FHIR setup wait limit reached" --region "$AWS_REGION" >/dev/null || true
  fail "The task did not stop within 10 minutes and was stopped."
fi

DESCRIPTION="$(aws ecs describe-tasks --cluster "$ECS_CLUSTER_NAME" --tasks "$TASK_ARN" --region "$AWS_REGION" --output json)"
EXIT_CODE="$(jq -r '.tasks[0].containers[0].exitCode // empty' <<<"$DESCRIPTION")"
STOPPED_REASON="$(jq -r '.tasks[0].stoppedReason // empty' <<<"$DESCRIPTION")"
if [[ "$EXIT_CODE" != "0" ]]; then
  fail "The FHIR setup task failed (exit code ${EXIT_CODE:-none}); see CloudWatch $LOG_GROUP."
fi

if [[ "$COMMAND" == "load" ]]; then
  mkdir -p "$(dirname "$RESOURCE_MAP_FILE")"
  aws s3 cp "s3://$DATA_BUCKET_NAME/$FHIR_RESOURCE_MAP_S3_KEY" "$RESOURCE_MAP_FILE" --only-show-errors --region "$AWS_REGION"
  "$REPO_ROOT/scripts/infrastructure/render_project_config.sh" --env-file "$ENV_FILE" --resource-map "$RESOURCE_MAP_FILE"
fi

STATUS="passed"
write_report
echo "FHIR setup $COMMAND passed."
