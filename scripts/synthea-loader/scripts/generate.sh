#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOADER_DIR="$(dirname "$SCRIPT_DIR")"

SYNTHEA_DIR="$LOADER_DIR/synthea"
CONFIG_FILE="$LOADER_DIR/config/synthea.properties"

POPULATION="${POPULATION:-10}"
SEED="${SEED:-12345}"
STATE="${STATE:-Washington}"

if [ ! -d "$SYNTHEA_DIR" ]; then
    echo "Synthea is not installed."
    echo "Run ./scripts/synthea-loader/scripts/install.sh first."
    exit 1
fi

echo "Generating Synthea population..."
echo "Population: $POPULATION"
echo "Seed:       $SEED"
echo "State:      $STATE"

cd "$SYNTHEA_DIR"

./run_synthea \
    -c "$CONFIG_FILE" \
    -s "$SEED" \
    -p "$POPULATION" \
    "$STATE"

echo "FHIR generation complete."

