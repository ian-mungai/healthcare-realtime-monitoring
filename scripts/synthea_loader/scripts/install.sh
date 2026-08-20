#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOADER_DIR="$(dirname "$SCRIPT_DIR")"
SYNTHEA_DIR="$LOADER_DIR/synthea"

if [ -d "$SYNTHEA_DIR" ]; then
    echo "Synthea already exists at $SYNTHEA_DIR"
    exit 0
fi

echo "Cloning Synthea..."

git clone https://github.com/synthetichealth/synthea.git "$SYNTHEA_DIR"

echo "Building Synthea..."

cd "$SYNTHEA_DIR"

./gradlew build check test

echo "Synthea installation complete."
