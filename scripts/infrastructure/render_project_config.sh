#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

exec "$PYTHON_BIN" "$REPO_ROOT/scripts/infrastructure/render_project_config.py" "$@"
