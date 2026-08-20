#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOADER_DIR="$(dirname "$SCRIPT_DIR")"
SYNTHEA_DIR="$LOADER_DIR/synthea"

POPULATION="${POPULATION:-10}"
SEED="${SEED:-12345}"
STATE="${STATE:-Washington}"

if [ ! -d "$SYNTHEA_DIR" ]; then
    echo "Synthea is not installed."
    echo "Run ./scripts/synthea-loader/scripts/install.sh first."
    exit 1
fi

cd "$SYNTHEA_DIR"

rm -rf output

echo "Generating Synthea population..."
echo "Population: $POPULATION"
echo "Seed:       $SEED"
echo "State:      $STATE"

./run_synthea \
    -s "$SEED" \
    -p "$POPULATION" \
    "$STATE"

echo
echo "Generated files:"
find output -maxdepth 3 -type f | sort