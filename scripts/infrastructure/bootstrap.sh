#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"
BOOTSTRAP_DIR="$REPO_ROOT/infra/bootstrap"
INFRA_DIR="$REPO_ROOT/infra"
ACTION="${1:-}"
CONFIRMATION="apply-healthcare-realtime-bootstrap"

usage() {
  cat <<'EOF'
Usage: scripts/infrastructure/bootstrap.sh <action>

Actions:
  state-plan   Initialize the local bootstrap stack and save a state-bucket plan.
  state-apply  Create the reviewed, protected Terraform state bucket.
  state-backup Save the local bootstrap state in the protected state bucket.
  main-init    Configure a fresh application stack to use the persistent bucket.
  main-migrate Migrate an existing application state into the persistent bucket.
  repositories-plan  Save a plan containing only the four ECR repositories.
  repositories-apply Apply the reviewed ECR repository plan.
  foundation-plan  Save the network, data-bucket, HAPI, dbt, and Soda foundation plan.
  foundation-apply Apply the reviewed foundation plan after images are published.
  application-plan Generate MWAA assets and save the complete application plan.
  application-apply Apply the reviewed complete application plan.

Set CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap for every apply or migration action.
EOF
}

require_confirmation() {
  if [[ "${CONFIRM_BOOTSTRAP:-}" != "$CONFIRMATION" ]]; then
    echo "Set CONFIRM_BOOTSTRAP=$CONFIRMATION before this action." >&2
    exit 2
  fi
}

write_backend_config() {
  local bucket region key
  bucket="$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket_name)"
  region="$(terraform -chdir="$BOOTSTRAP_DIR" output -raw aws_region)"
  key="$(terraform -chdir="$BOOTSTRAP_DIR" output -raw main_backend_key)"

  printf 'bucket = "%s"\nkey    = "%s"\nregion = "%s"\n' "$bucket" "$key" "$region" > "$INFRA_DIR/backend.hcl"
  echo "Wrote ignored backend configuration for the persistent state bucket."
}

application_plan_args=(-input=false -var-file=development.tfvars)

case "$ACTION" in
  state-plan)
    terraform -chdir="$BOOTSTRAP_DIR" init
    terraform -chdir="$BOOTSTRAP_DIR" plan -input=false -var-file=terraform.tfvars -out=tfplan-state-bootstrap
    terraform -chdir="$BOOTSTRAP_DIR" show -no-color tfplan-state-bootstrap
    ;;
  state-apply)
    require_confirmation
    terraform -chdir="$BOOTSTRAP_DIR" apply -input=false tfplan-state-bootstrap
    ;;
  state-backup)
    : "${TF_STATE_BUCKET:?Set TF_STATE_BUCKET in .env or the current shell.}"
    test -s "$BOOTSTRAP_DIR/terraform.tfstate"
    bootstrap_bucket="$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket_name)"
    bootstrap_state_key="$(terraform -chdir="$BOOTSTRAP_DIR" output -raw bootstrap_state_backup_key)"
    if [[ "$TF_STATE_BUCKET" != "$bootstrap_bucket" ]]; then
      echo "TF_STATE_BUCKET does not match the bucket managed by the bootstrap state." >&2
      exit 2
    fi
    aws s3api put-object \
      --bucket "$TF_STATE_BUCKET" \
      --key "$bootstrap_state_key" \
      --body "$BOOTSTRAP_DIR/terraform.tfstate" \
      --server-side-encryption AES256 \
      --region "${AWS_REGION:-${AWS_DEFAULT_REGION:-}}" \
      >/dev/null
    aws s3api head-object --bucket "$TF_STATE_BUCKET" --key "$bootstrap_state_key" --region "${AWS_REGION:-${AWS_DEFAULT_REGION:-}}" >/dev/null
    echo "Bootstrap state backup verified."
    ;;
  main-init)
    write_backend_config
    terraform -chdir="$INFRA_DIR" init -reconfigure -backend-config=backend.hcl
    ;;
  main-migrate)
    require_confirmation
    write_backend_config
    terraform -chdir="$INFRA_DIR" init -input=false -migrate-state -force-copy -backend-config=backend.hcl
    ;;
  repositories-plan)
    terraform -chdir="$INFRA_DIR" plan "${application_plan_args[@]}" \
      -target=module.vitals_simulator_ecs.aws_ecr_repository.vitals_simulator \
      -target=module.dbt_ecs.aws_ecr_repository.dbt \
      -target=module.soda_ecs.aws_ecr_repository.soda \
      -target=module.openlineage_collector.aws_ecr_repository.marquez \
      -out=tfplan-bootstrap-ecr
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-bootstrap-ecr
    ;;
  repositories-apply)
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-bootstrap-ecr
    ;;
  foundation-plan)
    terraform -chdir="$INFRA_DIR" plan "${application_plan_args[@]}" \
      -target=module.network \
      -target=module.raw_s3 \
      -target=module.hapi_ecs \
      -target=module.dbt_ecs \
      -target=module.soda_ecs \
      -out=tfplan-bootstrap-foundation
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-bootstrap-foundation
    ;;
  foundation-apply)
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-bootstrap-foundation
    ;;
  application-plan)
    for builder in "$REPO_ROOT"/scripts/lambda/build_*.sh; do
      "$builder"
    done
    "$REPO_ROOT/scripts/glue/build_lineage_package.sh"
    "$REPO_ROOT/airflow/serverless/convert_healthcare_realtime_pipeline.sh"
    "$REPO_ROOT/airflow/serverless/build_code_package.sh"
    terraform -chdir="$INFRA_DIR" plan "${application_plan_args[@]}" -out=tfplan-bootstrap-application
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-bootstrap-application
    ;;
  application-apply)
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-bootstrap-application
    ;;
  *)
    usage
    exit 2
    ;;
esac
