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
mkdir -p "${STAGING_DIR}/config"

cp "${REPO_ROOT}/services/__init__.py" "${STAGING_DIR}/services/__init__.py"
cp "${REPO_ROOT}/services/vital_signs.py" "${STAGING_DIR}/services/vital_signs.py"
# Package Python runtime files only; local receipts can contain authentication headers.
while IFS= read -r -d '' source_file; do
    relative_path="${source_file#${REPO_ROOT}/}"
    mkdir -p "${STAGING_DIR}/$(dirname "${relative_path}")"
    cp "${source_file}" "${STAGING_DIR}/${relative_path}"
done < <(find "${REPO_ROOT}/services/fhir_webhook/app" -type f -name '*.py' -print0)
cp "${REPO_ROOT}/services/fhir_webhook/__init__.py" "${STAGING_DIR}/services/fhir_webhook/__init__.py"
cp "${REPO_ROOT}/config/__init__.py" "${STAGING_DIR}/config/__init__.py"
cp "${REPO_ROOT}/config/vital_signs.json" "${STAGING_DIR}/config/vital_signs.json"

find "${STAGING_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${STAGING_DIR}" -type f -name "*.pyc" -delete

find "${STAGING_DIR}" -type f -exec touch -t 198001010000 {} +
rm -f "${OUTPUT_FILE}"

(
    cd "${STAGING_DIR}"
    find services config -type f -print | LC_ALL=C sort | zip -X -q "${OUTPUT_FILE}" -@
)

echo "FHIR webhook Lambda package created:"
echo "${OUTPUT_FILE}"
