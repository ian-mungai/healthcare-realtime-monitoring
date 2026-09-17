#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/build/glue"
OUTPUT_FILE="$OUTPUT_DIR/healthcare_realtime_lineage.zip"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/healthcare-realtime-glue.XXXXXX")"
trap 'rm -rf "$STAGING_DIR"' EXIT

mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_FILE"

mkdir -p "$STAGING_DIR/services" "$STAGING_DIR/config"
cp -R "$REPO_ROOT/lineage" "$STAGING_DIR/lineage"
cp "$REPO_ROOT/services/__init__.py" "$STAGING_DIR/services/__init__.py"
cp "$REPO_ROOT/services/vital_signs.py" "$STAGING_DIR/services/vital_signs.py"
cp "$REPO_ROOT/config/__init__.py" "$STAGING_DIR/config/__init__.py"
cp "$REPO_ROOT/config/vital_signs.json" "$STAGING_DIR/config/vital_signs.json"

find "$STAGING_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGING_DIR" -type f \( -name "*.pyc" -o -name ".DS_Store" \) -delete
find "$STAGING_DIR" -type f -exec touch -t 198001010000 {} +

(
  cd "$STAGING_DIR"
  find . -type f -print | LC_ALL=C sort | zip -X -q "$OUTPUT_FILE" -@
)

echo "Created $OUTPUT_FILE"
