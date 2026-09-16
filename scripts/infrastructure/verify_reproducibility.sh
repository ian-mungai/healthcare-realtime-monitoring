#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

for builder in "$REPO_ROOT"/scripts/lambda/build_*.sh; do
  "$builder"
done
"$REPO_ROOT/scripts/glue/build_lineage_package.sh"
"$REPO_ROOT/airflow/serverless/convert_healthcare_realtime_pipeline.sh"
"$REPO_ROOT/airflow/serverless/build_code_package.sh"

"$REPO_ROOT/.venv/bin/python" -m pytest \
  "$REPO_ROOT/tests/infrastructure/test_cleanup_storage.py" \
  "$REPO_ROOT/tests/infrastructure/test_iam_policy_tooling.py" \
  "$REPO_ROOT/tests/infrastructure/test_region_readiness.py" \
  -q

terraform -chdir="$REPO_ROOT/infra" test -filter=tests/ci_plan.tftest.hcl
terraform -chdir="$REPO_ROOT/infra/bootstrap" test -filter=tests/ci_plan.tftest.hcl

echo "Reproducibility simulation passed. A real clean-account deployment remains the release acceptance test."
