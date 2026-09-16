#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"

: "${AWS_REGION:?Set AWS_REGION in .env or the current shell.}"
: "${PROJECT_NAME:?Set PROJECT_NAME in .env or the current shell.}"
: "${TF_STATE_BUCKET:?Set TF_STATE_BUCKET in .env or the current shell.}"

TFVARS_FILE="${TERRAFORM_VAR_FILE:-$REPO_ROOT/infra/development.tfvars}"
CONFIG_KEY="$PROJECT_NAME/terraform/config/deployment.auto.tfvars.json"
TEMP_CONFIG="$(mktemp "${TMPDIR:-/tmp}/deployment-config.XXXXXX.json")"
trap 'rm -f "$TEMP_CONFIG"' EXIT

"$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/scripts/infrastructure/tfvars_to_json.py" \
  "$TFVARS_FILE" >"$TEMP_CONFIG"

jq -e \
  --arg aws_region "$AWS_REGION" \
  '(.project_name | type == "string" and length > 0) and .aws_region == $aws_region' \
  "$TEMP_CONFIG" >/dev/null

aws s3api put-object \
  --bucket "$TF_STATE_BUCKET" \
  --key "$CONFIG_KEY" \
  --body "$TEMP_CONFIG" \
  --content-type application/json \
  --server-side-encryption AES256 \
  --region "$AWS_REGION" \
  >/dev/null

encryption="$(aws s3api head-object \
  --bucket "$TF_STATE_BUCKET" \
  --key "$CONFIG_KEY" \
  --query ServerSideEncryption \
  --output text \
  --region "$AWS_REGION")"
test "$encryption" = "AES256"

echo "Private deployment configuration synchronized to encrypted, versioned AWS storage."
