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
}

# Terraform state is local and lives only as long as the deployment; teardown removes it. Each environment uses its own
# workspace (development the default one), so environments in separate AWS accounts never share a state file. See
# docs/environments.md.
environment_workspace() {
  local environment="${DEPLOYMENT_ENVIRONMENT:-development}"
  if [[ "$environment" == "development" ]]; then
    echo "default"
  else
    echo "$environment"
  fi
}

# Select, or create, the selected environment's workspace before any Terraform command in infra/.
select_environment_workspace() {
  local infra_dir="$1"
  if [[ ! -d "$infra_dir/.terraform" ]]; then
    terraform -chdir="$infra_dir" init -input=false >/dev/null
  fi
  terraform -chdir="$infra_dir" workspace select -or-create "$(environment_workspace)" >/dev/null
}
