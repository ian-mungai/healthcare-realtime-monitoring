#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/infrastructure/project_env.sh"
load_project_env "${PROJECT_ENV_FILE:-$REPO_ROOT/.env}"

export VITALS_API_ENDPOINT="$(terraform -chdir="$REPO_ROOT/infra" output -raw vitals_api_endpoint)"
export VITALS_WEBSOCKET_URL="$(terraform -chdir="$REPO_ROOT/infra" output -raw realtime_websocket_url)"
: "${PATIENT_IDS:?Set PATIENT_IDS in the project environment file.}"

cd "$REPO_ROOT"
exec env PYTHONPATH="$REPO_ROOT" "$REPO_ROOT/.venv/bin/python" -m streamlit run dashboard/app.py \
  --server.port "${LIVE_DASHBOARD_PORT:-8501}"
