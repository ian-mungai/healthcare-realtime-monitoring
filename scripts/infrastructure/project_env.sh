#!/usr/bin/env bash

load_project_env() {
  local env_file="${1:-.env}"
  [[ -f "$env_file" ]] || return 0

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      echo "Invalid environment assignment in $env_file: $line" >&2
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
