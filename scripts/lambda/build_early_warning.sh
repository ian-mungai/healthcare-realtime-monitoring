#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build/lambda"
STAGING_DIR="$(mktemp -d)"
OUTPUT_FILE="${BUILD_DIR}/early_warning.zip"

cleanup() {
    rm -rf "${STAGING_DIR}"
}

trap cleanup EXIT

mkdir -p "${BUILD_DIR}"
# Flat package: the modules import each other by these names when the services package is absent.
cp "${REPO_ROOT}/services/early_warning/handler.py" "${STAGING_DIR}/handler.py"
cp "${REPO_ROOT}/services/early_warning/scoring.py" "${STAGING_DIR}/scoring.py"
cp "${REPO_ROOT}/services/news2.py" "${STAGING_DIR}/news2.py"
cp "${REPO_ROOT}/services/feature_window.py" "${STAGING_DIR}/feature_window.py"
cp "${REPO_ROOT}/services/realtime_authorization.py" "${STAGING_DIR}/authorization.py"

find "${STAGING_DIR}" -type f -exec touch -t 198001010000 {} +
rm -f "${OUTPUT_FILE}"

(
    cd "${STAGING_DIR}"
    find . -type f -print | LC_ALL=C sort | zip -X -q "${OUTPUT_FILE}" -@
)

echo "Early-warning Lambda package created:"
echo "${OUTPUT_FILE}"
