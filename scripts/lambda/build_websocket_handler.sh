#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build/lambda"
STAGING_DIR="$(mktemp -d)"
OUTPUT_FILE="${BUILD_DIR}/websocket_handler.zip"

cleanup() {
    rm -rf "${STAGING_DIR}"
}

trap cleanup EXIT

mkdir -p "${BUILD_DIR}"
cp "${REPO_ROOT}/services/websocket_handler/handler.py" "${STAGING_DIR}/handler.py"

find "${STAGING_DIR}" -type f -exec touch -t 198001010000 {} +
rm -f "${OUTPUT_FILE}"

(
    cd "${STAGING_DIR}"
    find . -type f -print | LC_ALL=C sort | zip -X -q "${OUTPUT_FILE}" -@
)

echo "WebSocket handler Lambda package created:"
echo "${OUTPUT_FILE}"
