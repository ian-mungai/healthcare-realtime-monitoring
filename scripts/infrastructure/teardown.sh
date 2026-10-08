#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"
INFRA_DIR="$REPO_ROOT/infra"
select_environment_workspace "$INFRA_DIR"
ACTION="${1:-}"
ENVIRONMENT="${DEPLOYMENT_ENVIRONMENT:-development}"
CONFIRMATION="delete-healthcare-realtime-$ENVIRONMENT"
"$REPO_ROOT/scripts/infrastructure/render_project_config.sh"

usage() {
  cat <<'EOF'
Usage: scripts/infrastructure/teardown.sh <action>

Actions:
  prepare-plan     Build packages and save a plan that disables deletion protection.
  prepare-apply    Apply the reviewed protection-removal plan.
  cleanup-preview  Count application S3 versions and ECR images without deleting them.
  cleanup-apply    Empty application S3 buckets and ECR repositories.
  destroy-plan     Save the final Terraform destroy plan.
  destroy-apply    Apply the reviewed destroy plan, then remove the local state and saved plans.

Set CONFIRM_TEARDOWN=delete-healthcare-realtime-<environment> (for example -development) for every apply action.
Terraform state is local and not kept: destroy-apply removes it once it lists no resource.
EOF
}

require_confirmation() {
  if [[ "${CONFIRM_TEARDOWN:-}" != "$CONFIRMATION" ]]; then
    echo "Refusing destructive action. Set CONFIRM_TEARDOWN=$CONFIRMATION." >&2
    exit 2
  fi
}

# No state is kept after a teardown: once the destroy leaves nothing in state, delete the workspace's state files and
# the saved plans, which hold a copy of the state.
remove_local_state() {
  local remaining workspace state_dir
  workspace="$(environment_workspace)"
  state_dir="$INFRA_DIR"
  [[ "$workspace" == "default" ]] || state_dir="$INFRA_DIR/terraform.tfstate.d/$workspace"
  if [[ -f "$state_dir/terraform.tfstate" ]]; then
    remaining="$(terraform -chdir="$INFRA_DIR" state list)"
    if [[ -n "$remaining" ]]; then
      echo "Keeping the local state: it still lists $(wc -l <<<"$remaining" | tr -d ' ') resource(s)." >&2
      exit 1
    fi
  fi
  rm -f "$state_dir"/terraform.tfstate "$state_dir"/terraform.tfstate.*backup "$INFRA_DIR"/tfplan-*
  echo "Local Terraform state and saved plans removed."
}

build_packages() {
  local builder
  for builder in "$REPO_ROOT"/scripts/lambda/build_*.sh; do
    "$builder"
  done
  "$REPO_ROOT/scripts/glue/build_lineage_package.sh"
  "$REPO_ROOT/airflow/serverless/convert_healthcare_realtime_pipeline.sh"
  "$REPO_ROOT/airflow/serverless/build_code_package.sh"
}

build_or_verify_destroy_packages() {
  if terraform -chdir="$INFRA_DIR" output -json private_subnet_ids >/dev/null 2>&1; then
    build_packages
    return
  fi

  local required_files=(
    "$REPO_ROOT/build/lambda/early_warning.zip"
    "$REPO_ROOT/build/lambda/fhir_webhook.zip"
    "$REPO_ROOT/build/lambda/vitals_api.zip"
    "$REPO_ROOT/build/lambda/vitals_replay.zip"
    "$REPO_ROOT/build/lambda/vitals_stream_processor.zip"
    "$REPO_ROOT/build/lambda/websocket_handler.zip"
    "$REPO_ROOT/build/glue/healthcare_realtime_lineage.zip"
    "$REPO_ROOT/airflow/serverless/generated/healthcare_realtime_pipeline.yaml"
    "$REPO_ROOT/airflow/serverless/generated/healthcare_realtime_ingestion.yaml"
    "$REPO_ROOT/build/mwaa/healthcare_realtime_mwaa_serverless_code.zip"
  )
  local missing=0 required_file
  for required_file in "${required_files[@]}"; do
    if [[ ! -s "$required_file" ]]; then
      echo "Required destroy artifact is missing: $required_file" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    echo "Restore the build artifacts or backend state before retrying the destroy plan." >&2
    exit 2
  fi

  echo "Deployment outputs are incomplete after a partial destroy; reusing verified local artifacts."
}

terraform_plan_args=(
  -input=false
  -var-file=deployment.auto.tfvars.json
  -var=allow_destructive_teardown=true
  -var=openlineage_skip_final_snapshot=true
)

cleanup_args() {
  local data_bucket simulator_repository dbt_repository soda_repository marquez_repository grafana_repository
  local aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
  if [[ -z "$aws_region" ]]; then
    echo "Set AWS_REGION before inspecting or cleaning storage." >&2
    exit 2
  fi

  data_bucket="$(terraform -chdir="$INFRA_DIR" output -raw raw_s3_bucket_name)"
  simulator_repository="$(terraform -chdir="$INFRA_DIR" output -raw vitals_simulator_ecr_repository_name)"
  dbt_repository="$(basename "$(terraform -chdir="$INFRA_DIR" output -raw dbt_ecr_repository_url)")"
  soda_repository="$(basename "$(terraform -chdir="$INFRA_DIR" output -raw soda_ecr_repository_url)")"
  marquez_repository="$(basename "$(terraform -chdir="$INFRA_DIR" output -raw openlineage_collector_ecr_repository_url)")"
  grafana_repository="$(basename "$(terraform -chdir="$INFRA_DIR" output -raw grafana_ecr_repository_url)")"

  CLEANUP_ARGS=(
    --region "$aws_region"
    --s3-bucket "$data_bucket"
    --ecr-repository "$simulator_repository"
    --ecr-repository "$dbt_repository"
    --ecr-repository "$soda_repository"
    --ecr-repository "$marquez_repository"
    --ecr-repository "$grafana_repository"
  )
  if [[ -n "${AWS_PROFILE:-}" ]]; then
    CLEANUP_ARGS+=(--profile "$AWS_PROFILE")
  fi
}

case "$ACTION" in
  prepare-plan)
    build_packages
    terraform -chdir="$INFRA_DIR" plan "${terraform_plan_args[@]}" -out=tfplan-teardown-prepare-$ENVIRONMENT
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-teardown-prepare-$ENVIRONMENT
    ;;
  prepare-apply)
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-teardown-prepare-$ENVIRONMENT
    ;;
  cleanup-preview)
    cleanup_args
    "$REPO_ROOT/.venv/bin/python" -m scripts.infrastructure.cleanup_storage "${CLEANUP_ARGS[@]}"
    ;;
  cleanup-apply)
    require_confirmation
    cleanup_args
    "$REPO_ROOT/.venv/bin/python" -m scripts.infrastructure.cleanup_storage "${CLEANUP_ARGS[@]}" --execute --confirm "$CONFIRMATION"
    ;;
  destroy-plan)
    build_or_verify_destroy_packages
    terraform -chdir="$INFRA_DIR" plan -destroy "${terraform_plan_args[@]}" -out=tfplan-teardown-destroy-$ENVIRONMENT
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-teardown-destroy-$ENVIRONMENT
    ;;
  destroy-apply)
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-teardown-destroy-$ENVIRONMENT
    remove_local_state
    ;;
  *)
    usage
    exit 2
    ;;
esac
