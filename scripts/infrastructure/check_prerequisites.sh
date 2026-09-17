#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"
PHASE="${1:-post-deploy}"

case "$PHASE" in
  local | pre-deploy | post-deploy) ;;
  *)
    echo "Usage: scripts/infrastructure/check_prerequisites.sh [local|pre-deploy|post-deploy]" >&2
    exit 2
    ;;
esac

failures=0

pass() {
  printf 'PASS  %s\n' "$1"
}

fail() {
  printf 'FAIL  %s\n' "$1" >&2
  failures=$((failures + 1))
}

check_command() {
  command -v "$1" >/dev/null 2>&1 && pass "tool: $1" || fail "tool missing: $1"
}

check_env() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" || "$value" == *'<'* || "$value" == *'>'* ]]; then
    fail "environment: $name"
  else
    pass "environment: $name"
  fi
}

required_commands=(aws terraform docker git java jq)
if [[ "$PHASE" == "post-deploy" ]]; then
  required_commands+=(gh)
fi
for command_name in "${required_commands[@]}"; do
  check_command "$command_name"
done

required_variables=(AWS_PROFILE AWS_REGION PROJECT_NAME TF_STATE_BUCKET FHIR_WEBHOOK_SECRET_ID FHIR_WEBHOOK_SECRET_KEY)
if [[ "$PHASE" == "post-deploy" ]]; then
  required_variables+=(GITHUB_REPOSITORY GITHUB_DEPLOYMENT_ENVIRONMENT)
fi
for variable_name in "${required_variables[@]}"; do
  check_env "$variable_name"
done

if ((failures > 0)); then
  echo "Local prerequisite checks failed; cloud checks were skipped." >&2
  exit 1
fi

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
EXPECTED_STATE_PREFIX="${PROJECT_NAME}/terraform"
[[ "$TF_STATE_PREFIX" == "$EXPECTED_STATE_PREFIX" ]] \
  && pass "Terraform state prefix" || fail "TF_STATE_PREFIX must equal <project-name>/terraform"
TF_STATE_KEY="${TF_STATE_PREFIX}/terraform.tfstate"
TF_BOOTSTRAP_STATE_KEY="${TF_STATE_PREFIX}/bootstrap/terraform.tfstate"
TF_DEPLOYMENT_CONFIG_KEY="${TF_STATE_PREFIX}/config/deployment.auto.tfvars.json"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if "$REPO_ROOT/scripts/infrastructure/render_project_config.sh" >/dev/null; then
  pass "single-source project configuration"
else
  fail "single-source project configuration"
fi

python_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
[[ "$python_version" == "3.12" ]] && pass "Python 3.12 environment" || fail "Python 3.12 environment"
terraform version -json 2>/dev/null \
  | jq -e '.terraform_version | split(".") | (.[0] | tonumber) > 1 or ((.[0] | tonumber) == 1 and (.[1] | tonumber) >= 11)' >/dev/null \
  && pass "Terraform 1.11+" || fail "Terraform 1.11+"
java_version="$(java -version 2>&1 | head -n 1 | sed -E 's/.*version "([0-9]+).*/\1/')"
[[ "$java_version" =~ ^[0-9]+$ && "$java_version" -ge 17 ]] && pass "Java 17+" || fail "Java 17+"

aws sts get-caller-identity >/dev/null && pass "AWS identity" || fail "AWS identity"
docker info >/dev/null 2>&1 && pass "Docker daemon" || fail "Docker daemon"

if [[ "$PHASE" == "local" ]]; then
  if ((failures > 0)); then
    printf '%d local prerequisite check(s) failed.\n' "$failures" >&2
    exit 1
  fi
  echo "Local prerequisite checks passed."
  exit 0
fi

region_check_args=(--region "$AWS_REGION")
if [[ -n "${AWS_PROFILE:-}" ]]; then
  region_check_args+=(--profile "$AWS_PROFILE")
fi
"$PYTHON_BIN" "$REPO_ROOT/scripts/infrastructure/check_region_readiness.py" "${region_check_args[@]}" \
  && pass "regional readiness" || fail "regional readiness"

registered_secret="$(aws secretsmanager list-secrets --query "SecretList[?Name=='$FHIR_WEBHOOK_SECRET_ID'].Name | [0]" --output text 2>/dev/null || true)"
if [[ "$registered_secret" == "$FHIR_WEBHOOK_SECRET_ID" ]]; then
  pass "FHIR webhook secret registration"
else
  fail "FHIR webhook secret registration"
fi

policy_inventory="$(aws iam list-policies --scope Local --query 'Policies[].PolicyName' --output json 2>/dev/null || echo '[]')"
missing_policies=0
for policy_path in "$REPO_ROOT"/infra/iam/policies/*.json; do
  policy_name="$(basename "$policy_path" .json)"
  jq -e --arg name "$policy_name" 'index($name) != null' <<<"$policy_inventory" >/dev/null \
    || { fail "customer-managed policy missing: $policy_name"; missing_policies=$((missing_policies + 1)); }
done
if ((missing_policies == 0)); then
  pass "customer-managed policy inventory"
fi

if [[ "$PHASE" == "pre-deploy" ]]; then
  if ((failures > 0)); then
    printf '%d pre-deployment prerequisite check(s) failed.\n' "$failures" >&2
    exit 1
  fi
  echo "Pre-deployment prerequisite checks passed."
  exit 0
fi

gh auth status >/dev/null 2>&1 && pass "GitHub CLI authentication" || fail "GitHub CLI authentication"

if aws s3api head-object --bucket "$TF_STATE_BUCKET" --key "$TF_STATE_KEY" >/dev/null 2>&1; then
  pass "main Terraform state"
else
  fail "main Terraform state"
fi
if aws s3api head-object --bucket "$TF_STATE_BUCKET" --key "$TF_BOOTSTRAP_STATE_KEY" >/dev/null 2>&1; then
  pass "bootstrap Terraform state backup"
else
  fail "bootstrap Terraform state backup"
fi
deployment_config_encryption="$(aws s3api head-object \
  --bucket "$TF_STATE_BUCKET" \
  --key "$TF_DEPLOYMENT_CONFIG_KEY" \
  --query ServerSideEncryption \
  --output text 2>/dev/null || true)"
[[ "$deployment_config_encryption" == "AES256" || "$deployment_config_encryption" == "aws:kms" ]] \
  && pass "encrypted private deployment configuration" || fail "encrypted private deployment configuration"

[[ "$(aws s3api get-bucket-versioning --bucket "$TF_STATE_BUCKET" --query Status --output text 2>/dev/null)" == "Enabled" ]] \
  && pass "state bucket versioning" || fail "state bucket versioning"
bucket_encryption="$(aws s3api get-bucket-encryption --bucket "$TF_STATE_BUCKET" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text 2>/dev/null || true)"
[[ "$bucket_encryption" == "AES256" || "$bucket_encryption" == "aws:kms" ]] \
  && pass "state bucket encryption" || fail "state bucket encryption"
[[ "$(aws s3api get-public-access-block --bucket "$TF_STATE_BUCKET" --query 'PublicAccessBlockConfiguration.[BlockPublicAcls,IgnorePublicAcls,BlockPublicPolicy,RestrictPublicBuckets]' --output text 2>/dev/null)" == $'True\tTrue\tTrue\tTrue' ]] \
  && pass "state bucket public access block" || fail "state bucket public access block"

github_oidc_found=false
while IFS= read -r oidc_arn; do
  if [[ "$(aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$oidc_arn" --query Url --output text 2>/dev/null)" == "token.actions.githubusercontent.com" ]]; then
    github_oidc_found=true
    break
  fi
done < <(aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text 2>/dev/null | tr '\t' '\n')
if [[ "$github_oidc_found" == true ]]; then
  pass "GitHub OIDC provider"
else
  fail "GitHub OIDC provider"
fi

github_region="$(gh variable get AWS_REGION --repo "$GITHUB_REPOSITORY" --env "$GITHUB_DEPLOYMENT_ENVIRONMENT" 2>/dev/null || true)"
[[ "$github_region" == "$AWS_REGION" ]] && pass "GitHub AWS_REGION" || fail "GitHub AWS_REGION"
github_variables="$(gh variable list --repo "$GITHUB_REPOSITORY" --env "$GITHUB_DEPLOYMENT_ENVIRONMENT" --json name --jq '.[].name' 2>/dev/null || true)"
if grep -Eq '^(AWS_DEPLOY_ROLE_ARN|TF_STATE_BUCKET|TF_STATE_PREFIX|TERRAFORM_VARIABLES_JSON)$' <<<"$github_variables"; then
  fail "GitHub environment variables contain private deployment identifiers"
else
  pass "GitHub environment variables contain no private deployment identifiers"
fi
github_secrets="$(gh secret list --repo "$GITHUB_REPOSITORY" --env "$GITHUB_DEPLOYMENT_ENVIRONMENT" --json name --jq '.[].name' 2>/dev/null || true)"
for secret_name in AWS_DEPLOY_ROLE_ARN TF_STATE_BUCKET TF_STATE_PREFIX; do
  grep -Fxq "$secret_name" <<<"$github_secrets" \
    && pass "GitHub secret: $secret_name" || fail "GitHub secret: $secret_name"
done
if grep -Fxq TERRAFORM_VARIABLES_JSON <<<"$github_secrets"; then
  fail "obsolete GitHub bulk Terraform secret"
else
  pass "obsolete GitHub bulk Terraform secret removed"
fi

alert_topic_arn="$(terraform -chdir="$REPO_ROOT/infra" output -raw realtime_alert_topic_arn 2>/dev/null || true)"
confirmed_subscriptions="$(aws sns list-subscriptions-by-topic --topic-arn "$alert_topic_arn" --query 'length(Subscriptions[?SubscriptionArn != `PendingConfirmation`])' --output text 2>/dev/null || echo 0)"
[[ "$confirmed_subscriptions" =~ ^[1-9][0-9]*$ ]] && pass "confirmed alert subscription" || fail "confirmed alert subscription"

if ((failures > 0)); then
  printf '%d prerequisite check(s) failed.\n' "$failures" >&2
  exit 1
fi

echo "Post-deployment prerequisite checks passed."
