#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"

: "${AWS_REGION:?Set AWS_REGION in .env or the current shell.}"
: "${PROJECT_NAME:?Set PROJECT_NAME in .env or the current shell.}"
: "${TF_STATE_BUCKET:?Set TF_STATE_BUCKET in .env or the current shell.}"

EXPECTED_STATE_PREFIX="$PROJECT_NAME/terraform"
if [[ "$TF_STATE_PREFIX" != "$EXPECTED_STATE_PREFIX" ]]; then
  echo "TF_STATE_PREFIX must equal <project-name>/terraform." >&2
  exit 1
fi

"$REPO_ROOT/scripts/infrastructure/render_project_config.sh"
TFVARS_FILE="$REPO_ROOT/infra/deployment.auto.tfvars.json"
CONFIG_KEY="$TF_STATE_PREFIX/config/deployment.auto.tfvars.json"

jq -e \
  --arg aws_region "$AWS_REGION" \
  '(.project_name | type == "string" and length > 0) and .aws_region == $aws_region' \
  "$TFVARS_FILE" >/dev/null

aws s3api put-object \
  --bucket "$TF_STATE_BUCKET" \
  --key "$CONFIG_KEY" \
  --body "$TFVARS_FILE" \
  --content-type application/json \
  --region "$AWS_REGION" \
  >/dev/null

encryption="$(aws s3api head-object \
  --bucket "$TF_STATE_BUCKET" \
  --key "$CONFIG_KEY" \
  --query ServerSideEncryption \
  --output text \
  --region "$AWS_REGION")"
case "$encryption" in
  AES256 | aws:kms) ;;
  *)
    echo "Private deployment configuration is not encrypted by the state bucket." >&2
    exit 1
    ;;
esac

echo "Private deployment configuration synchronized to encrypted, versioned AWS storage."
