#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build/lambda"
STAGING_DIR="$(mktemp -d)"
OUTPUT_FILE="${BUILD_DIR}/vitals_stream_processor.zip"

cleanup() {
    rm -rf "${STAGING_DIR}"
}

trap cleanup EXIT

mkdir -p "${BUILD_DIR}"

cp "${REPO_ROOT}/services/vitals_stream_processor/handler.py" "${STAGING_DIR}/handler.py"
cp "${REPO_ROOT}/services/vitals_stream_processor/schema.py" "${STAGING_DIR}/schema.py"

find "${STAGING_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${STAGING_DIR}" -type f -name "*.pyc" -delete

find "${STAGING_DIR}" -type f -exec touch -t 198001010000 {} +

rm -f "${OUTPUT_FILE}"

(
    cd "${STAGING_DIR}"
    find . -type f -print | LC_ALL=C sort | zip -X -q "${OUTPUT_FILE}" -@
)

echo "Vitals stream processor Lambda package created:"
echo "${OUTPUT_FILE}"