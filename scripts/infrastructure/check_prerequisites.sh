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
for command_name in "${required_commands[@]}"; do
  check_command "$command_name"
done

required_variables=(AWS_PROFILE AWS_REGION PROJECT_NAME FHIR_WEBHOOK_SECRET_ID FHIR_WEBHOOK_SECRET_KEY)
for variable_name in "${required_variables[@]}"; do
  check_env "$variable_name"
done

if ((failures > 0)); then
  echo "Local prerequisite checks failed; cloud checks were skipped." >&2
  exit 1
fi

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

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

caller_account="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
[[ -n "$caller_account" ]] && pass "AWS identity" || fail "AWS identity"
[[ -n "$caller_account" && "$caller_account" == "${AWS_ACCOUNT_ID:-}" ]] \
  && pass "AWS account matches the selected environment file" || fail "AWS account does not match AWS_ACCOUNT_ID in the selected environment file"
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

if [[ "${ENABLE_GRAFANA:-false}" == "true" ]]; then
  grafana_secret="$(aws secretsmanager list-secrets --query "SecretList[?Name=='healthcare-realtime/grafana-admin'].Name | [0]" --output text 2>/dev/null || true)"
  if [[ "$grafana_secret" == "healthcare-realtime/grafana-admin" ]]; then
    pass "Grafana admin secret registration"
  else
    fail "Grafana admin secret registration"
  fi
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

# Terraform state is local to this checkout and the selected environment's workspace; teardown removes it.
select_environment_workspace "$REPO_ROOT/infra"
[[ -n "$(terraform -chdir="$REPO_ROOT/infra" state list 2>/dev/null)" ]] \
  && pass "local Terraform state of the deployment" || fail "local Terraform state of the deployment"

alert_topic_arn="$(terraform -chdir="$REPO_ROOT/infra" output -raw realtime_alert_topic_arn 2>/dev/null || true)"
confirmed_subscriptions="$(aws sns list-subscriptions-by-topic --topic-arn "$alert_topic_arn" --query 'length(Subscriptions[?SubscriptionArn != `PendingConfirmation`])' --output text 2>/dev/null || echo 0)"
[[ "$confirmed_subscriptions" =~ ^[1-9][0-9]*$ ]] && pass "confirmed alert subscription" || fail "confirmed alert subscription"

if ((failures > 0)); then
  printf '%d prerequisite check(s) failed.\n' "$failures" >&2
  exit 1
fi

echo "Post-deployment prerequisite checks passed."
