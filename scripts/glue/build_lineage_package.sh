#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/tmp"
OUTPUT_FILE="$OUTPUT_DIR/healthcare_realtime_lineage.zip"

mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_FILE"

cd "$REPO_ROOT"

zip -r "$OUTPUT_FILE" \
  lineage \
  -x '*/__pycache__/*' \
  -x '*.pyc' \
  -x '.DS_Store'

echo "Created $OUTPUT_FILE"