#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INFRA_DIR="$REPO_ROOT/infra"
ACTION="${1:-}"
CONFIRMATION="delete-healthcare-realtime-development"

usage() {
  cat <<'EOF'
Usage: scripts/infrastructure/teardown.sh <action>

Actions:
  prepare-plan     Build packages and save a plan that disables deletion protection.
  prepare-apply    Apply the reviewed protection-removal plan.
  cleanup-preview  Count application S3 versions and ECR images without deleting them.
  cleanup-apply    Empty application S3 buckets and ECR repositories.
  destroy-plan     Save the final Terraform destroy plan.
  destroy-apply    Apply the reviewed destroy plan.

Set CONFIRM_TEARDOWN=delete-healthcare-realtime-development for every apply action.
Set TF_STATE_BUCKET to the separate persistent state bucket before cleanup or destroy.
EOF
}

require_confirmation() {
  if [[ "${CONFIRM_TEARDOWN:-}" != "$CONFIRMATION" ]]; then
    echo "Refusing destructive action. Set CONFIRM_TEARDOWN=$CONFIRMATION." >&2
    exit 2
  fi
}

require_separate_state_bucket() {
  if [[ -z "${TF_STATE_BUCKET:-}" ]]; then
    echo "TF_STATE_BUCKET must name the separate persistent Terraform state bucket." >&2
    exit 2
  fi

  local data_bucket
  data_bucket="$(terraform -chdir="$INFRA_DIR" output -raw raw_s3_bucket_name)"
  if [[ "$TF_STATE_BUCKET" == "$data_bucket" ]]; then
    echo "Refusing teardown because Terraform state is stored in the application data bucket." >&2
    exit 2
  fi
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

terraform_plan_args=(
  -input=false
  -var-file=development.tfvars
  -var=allow_destructive_teardown=true
  -var=openlineage_skip_final_snapshot=true
)

cleanup_args() {
  local data_bucket mwaa_bucket simulator_repository dbt_repository soda_repository marquez_repository
  local aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
  if [[ -z "$aws_region" ]]; then
    echo "Set AWS_REGION before inspecting or cleaning storage." >&2
    exit 2
  fi

  data_bucket="$(terraform -chdir="$INFRA_DIR" output -raw raw_s3_bucket_name)"
  mwaa_bucket="$(terraform -chdir="$INFRA_DIR" output -raw mwaa_source_bucket_name)"
  simulator_repository="$(terraform -chdir="$INFRA_DIR" output -raw vitals_simulator_ecr_repository_name)"
  dbt_repository="$(basename "$(terraform -chdir="$INFRA_DIR" output -raw dbt_ecr_repository_url)")"
  soda_repository="$(basename "$(terraform -chdir="$INFRA_DIR" output -raw soda_ecr_repository_url)")"
  marquez_repository="$(basename "$(terraform -chdir="$INFRA_DIR" output -raw openlineage_collector_ecr_repository_url)")"

  CLEANUP_ARGS=(
    --region "$aws_region"
    --s3-bucket "$data_bucket"
    --s3-bucket "$mwaa_bucket"
    --protected-bucket "$TF_STATE_BUCKET"
    --ecr-repository "$simulator_repository"
    --ecr-repository "$dbt_repository"
    --ecr-repository "$soda_repository"
    --ecr-repository "$marquez_repository"
  )
  if [[ -n "${AWS_PROFILE:-}" ]]; then
    CLEANUP_ARGS+=(--profile "$AWS_PROFILE")
  fi
}

case "$ACTION" in
  prepare-plan)
    require_separate_state_bucket
    build_packages
    terraform -chdir="$INFRA_DIR" plan "${terraform_plan_args[@]}" -out=tfplan-teardown-prepare
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-teardown-prepare
    ;;
  prepare-apply)
    require_confirmation
    require_separate_state_bucket
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-teardown-prepare
    ;;
  cleanup-preview)
    require_separate_state_bucket
    cleanup_args
    "$REPO_ROOT/.venv/bin/python" -m scripts.infrastructure.cleanup_storage "${CLEANUP_ARGS[@]}"
    ;;
  cleanup-apply)
    require_confirmation
    require_separate_state_bucket
    cleanup_args
    "$REPO_ROOT/.venv/bin/python" -m scripts.infrastructure.cleanup_storage "${CLEANUP_ARGS[@]}" --execute --confirm "$CONFIRMATION"
    ;;
  destroy-plan)
    require_separate_state_bucket
    build_packages
    terraform -chdir="$INFRA_DIR" plan -destroy "${terraform_plan_args[@]}" -out=tfplan-teardown-destroy
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-teardown-destroy
    ;;
  destroy-apply)
    require_confirmation
    require_separate_state_bucket
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-teardown-destroy
    ;;
  *)
    usage
    exit 2
    ;;
esac
