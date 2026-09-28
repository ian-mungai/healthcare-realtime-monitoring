#!/usr/bin/env bash

load_project_env() {
  local env_file="${1:-.env}"
  [[ -f "$env_file" ]] || return 0

  local line key value
  local line_number=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      echo "Invalid environment assignment in $env_file at line $line_number" >&2
      return 2
    fi

    key="${line%%=*}"
    value="${line#*=}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$env_file"

  if [[ -n "${PROJECT_NAME:-}" ]]; then
    local derived_state_prefix="${PROJECT_NAME}/terraform"
    TF_STATE_PREFIX="$derived_state_prefix"
    export TF_STATE_PREFIX
  fi

}

# Stop before Terraform touches another environment's state: infra/ must be initialized for the state bucket that the
# selected environment file names. Environments live in separate AWS accounts; see docs/environments.md.
require_selected_backend() {
  local infra_dir="$1"
  local initialized="$infra_dir/.terraform/terraform.tfstate"
  [[ -f "$initialized" ]] || return 0
  local bucket
  bucket="$(jq -r '.backend.config.bucket // empty' "$initialized")"
  if [[ -n "$bucket" && "$bucket" != "${TF_STATE_BUCKET:-}" ]]; then
    echo "infra/ is initialized for a different environment than ${PROJECT_ENV_FILE:-.env} selects." >&2
    echo "Run ./scripts/infrastructure/bootstrap.sh main-init with the same PROJECT_ENV_FILE before continuing." >&2
    return 2
  fi
}

# Bootstrap state is local; each environment uses its own Terraform workspace so accounts never share it.
bootstrap_workspace() {
  local environment="${DEPLOYMENT_ENVIRONMENT:-development}"
  if [[ "$environment" == "development" ]]; then
    echo "default"
  else
    echo "$environment"
  fi
}
