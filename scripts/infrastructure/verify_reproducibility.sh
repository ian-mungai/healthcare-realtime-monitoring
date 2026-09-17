#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/healthcare-realtime-reproducibility.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT

if [[ -z "${PYTHON_BIN:-}" && -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

ARTIFACTS=(
  "$REPO_ROOT/build/lambda/fhir_webhook.zip"
  "$REPO_ROOT/build/lambda/vitals_api.zip"
  "$REPO_ROOT/build/lambda/vitals_replay.zip"
  "$REPO_ROOT/build/lambda/vitals_stream_processor.zip"
  "$REPO_ROOT/build/lambda/websocket_handler.zip"
  "$REPO_ROOT/build/glue/healthcare_realtime_lineage.zip"
  "$REPO_ROOT/build/mwaa/healthcare_realtime_mwaa_serverless_code.zip"
)

build_artifacts() {
  local builder
  for builder in "$REPO_ROOT"/scripts/lambda/build_*.sh; do
    "$builder"
  done
  "$REPO_ROOT/scripts/glue/build_lineage_package.sh"
  "$REPO_ROOT/airflow/serverless/convert_healthcare_realtime_pipeline.sh"
  "$REPO_ROOT/airflow/serverless/build_code_package.sh"
}

write_checksums() {
  local manifest="$1"
  "$PYTHON_BIN" - "$manifest" "$REPO_ROOT" "${ARTIFACTS[@]}" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

manifest = Path(sys.argv[1])
repository = Path(sys.argv[2])
artifacts = [Path(value) for value in sys.argv[3:]]
missing = [str(path) for path in artifacts if not path.is_file()]
if missing:
    raise SystemExit(f"Missing build artifacts: {', '.join(missing)}")
manifest.write_text(
    "".join(f"{sha256(path.read_bytes()).hexdigest()}  {path.relative_to(repository)}\n" for path in artifacts),
    encoding="utf-8",
)
PY
}

build_artifacts
write_checksums "$TEMP_DIR/first.sha256"
build_artifacts
write_checksums "$TEMP_DIR/second.sha256"

if ! cmp -s "$TEMP_DIR/first.sha256" "$TEMP_DIR/second.sha256"; then
  diff -u "$TEMP_DIR/first.sha256" "$TEMP_DIR/second.sha256" || true
  echo "Build artifacts are not reproducible." >&2
  exit 1
fi

"$REPO_ROOT/.venv/bin/python" -m pytest \
  "$REPO_ROOT/tests/infrastructure/test_cleanup_storage.py" \
  "$REPO_ROOT/tests/infrastructure/test_iam_policy_tooling.py" \
  "$REPO_ROOT/tests/infrastructure/test_region_readiness.py" \
  -q

terraform -chdir="$REPO_ROOT/infra" test -filter=tests/ci_plan.tftest.hcl
terraform -chdir="$REPO_ROOT/infra/bootstrap" test -filter=tests/ci_plan.tftest.hcl

echo "Reproducibility verification passed: two builds produced identical artifact checksums."
echo "A real clean-account deployment remains the release acceptance test."
