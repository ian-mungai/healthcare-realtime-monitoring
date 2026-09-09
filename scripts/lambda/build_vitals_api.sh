#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build/lambda"
STAGING_DIR="$(mktemp -d)"
OUTPUT_FILE="${BUILD_DIR}/vitals_api.zip"

cleanup() {
    rm -rf "${STAGING_DIR}"
}

trap cleanup EXIT

mkdir -p "${BUILD_DIR}"
cp "${REPO_ROOT}/services/vitals_api/handler.py" "${STAGING_DIR}/handler.py"
cp "${REPO_ROOT}/services/realtime_authorization.py" "${STAGING_DIR}/authorization.py"

find "${STAGING_DIR}" -type f -exec touch -t 198001010000 {} +
rm -f "${OUTPUT_FILE}"

(
    cd "${STAGING_DIR}"
    find . -type f -print | LC_ALL=C sort | zip -X -q "${OUTPUT_FILE}" -@
)

echo "Vitals API Lambda package created:"
echo "${OUTPUT_FILE}"
