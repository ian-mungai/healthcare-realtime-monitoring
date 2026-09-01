#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build/lambda"
STAGING_DIR="$(mktemp -d)"
OUTPUT_FILE="${BUILD_DIR}/fhir_webhook.zip"

cleanup() {
    rm -rf "${STAGING_DIR}"
}

trap cleanup EXIT

mkdir -p "${BUILD_DIR}"
mkdir -p "${STAGING_DIR}/services"

cp "${REPO_ROOT}/services/__init__.py" "${STAGING_DIR}/services/__init__.py"
cp -R "${REPO_ROOT}/services/fhir_webhook" "${STAGING_DIR}/services/fhir_webhook"

rm -rf "${STAGING_DIR}/services/fhir_webhook/tests"

find "${STAGING_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${STAGING_DIR}" -type f -name "*.pyc" -delete

find "${STAGING_DIR}" -type f -exec touch -t 198001010000 {} +
rm -f "${OUTPUT_FILE}"

(
    cd "${STAGING_DIR}"
    find services -type f -print | LC_ALL=C sort | zip -X -q "${OUTPUT_FILE}" -@
)

echo "FHIR webhook Lambda package created:"
echo "${OUTPUT_FILE}"