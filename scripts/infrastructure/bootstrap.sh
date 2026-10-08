#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"
INFRA_DIR="$REPO_ROOT/infra"
ACTION="${1:-}"
CONFIRMATION="apply-healthcare-realtime-bootstrap"
ENVIRONMENT="${DEPLOYMENT_ENVIRONMENT:-development}"
"$REPO_ROOT/scripts/infrastructure/render_project_config.sh"

usage() {
  cat <<'EOF'
Usage: scripts/infrastructure/bootstrap.sh <action>

Actions:
  init         Initialize infra/ with local state in the selected environment's workspace.
  repositories-plan  Save a plan containing only the five ECR repositories.
  repositories-apply Apply the reviewed ECR repository plan.
  foundation-plan  Save the network, data-bucket, HAPI, Glue, dbt, and Soda foundation plan.
  foundation-apply Apply the reviewed foundation plan after images are published.
  application-plan Generate MWAA assets and save the complete application plan.
  application-apply Apply the reviewed complete application plan.

Set CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap for every apply action. Terraform state is local and
teardown removes it; nothing is kept between deployments.
EOF
}

require_confirmation() {
  if [[ "${CONFIRM_BOOTSTRAP:-}" != "$CONFIRMATION" ]]; then
    echo "Set CONFIRM_BOOTSTRAP=$CONFIRMATION before this action." >&2
    exit 2
  fi
}

# Name the environment's rendered variable file explicitly on every plan.
application_plan_args=(-input=false -var-file=deployment.auto.tfvars.json)

case "$ACTION" in
  init)
    terraform -chdir="$INFRA_DIR" init -input=false
    select_environment_workspace "$INFRA_DIR"
    ;;
  repositories-plan)
    select_environment_workspace "$INFRA_DIR"
    terraform -chdir="$INFRA_DIR" plan "${application_plan_args[@]}" \
      -target=module.vitals_simulator_ecs.aws_ecr_repository.vitals_simulator \
      -target=module.dbt_ecs.aws_ecr_repository.dbt \
      -target=module.soda_ecs.aws_ecr_repository.soda \
      -target=module.openlineage_collector.aws_ecr_repository.marquez \
      -target=module.grafana_ecs.aws_ecr_repository.grafana \
      -out=tfplan-bootstrap-ecr-$ENVIRONMENT
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-bootstrap-ecr-$ENVIRONMENT
    ;;
  repositories-apply)
    select_environment_workspace "$INFRA_DIR"
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-bootstrap-ecr-$ENVIRONMENT
    ;;
  foundation-plan)
    select_environment_workspace "$INFRA_DIR"
    "$REPO_ROOT/scripts/glue/build_lineage_package.sh"
    terraform -chdir="$INFRA_DIR" plan "${application_plan_args[@]}" \
      -target=module.network \
      -target=module.raw_s3 \
      -target=module.hapi_ecs \
      -target=module.fhir_setup_ecs \
      -target=module.glue \
      -target=module.dbt_ecs \
      -target=module.soda_ecs \
      -out=tfplan-bootstrap-foundation-$ENVIRONMENT
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-bootstrap-foundation-$ENVIRONMENT
    ;;
  foundation-apply)
    select_environment_workspace "$INFRA_DIR"
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-bootstrap-foundation-$ENVIRONMENT
    ;;
  application-plan)
    select_environment_workspace "$INFRA_DIR"
    for builder in "$REPO_ROOT"/scripts/lambda/build_*.sh; do
      "$builder"
    done
    "$REPO_ROOT/scripts/glue/build_lineage_package.sh"
    "$REPO_ROOT/airflow/serverless/convert_healthcare_realtime_pipeline.sh"
    "$REPO_ROOT/airflow/serverless/build_code_package.sh"
    terraform -chdir="$INFRA_DIR" plan "${application_plan_args[@]}" -out=tfplan-bootstrap-application-$ENVIRONMENT
    terraform -chdir="$INFRA_DIR" show -no-color tfplan-bootstrap-application-$ENVIRONMENT
    ;;
  application-apply)
    select_environment_workspace "$INFRA_DIR"
    require_confirmation
    terraform -chdir="$INFRA_DIR" apply -input=false tfplan-bootstrap-application-$ENVIRONMENT
    ;;
  *)
    usage
    exit 2
    ;;
esac
