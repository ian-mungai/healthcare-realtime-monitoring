#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOADER_DIR="$(dirname "$SCRIPT_DIR")"
SYNTHEA_DIR="$LOADER_DIR/synthea"

POPULATION="${POPULATION:-100}"
SEED="${SEED:-4817263}"
STATE="${STATE:-Washington}"
# Adults only: the BIDMC waveforms and the NEWS2-based label are adult measures.
AGE_RANGE="${AGE_RANGE:-18-90}"

if [ ! -d "$SYNTHEA_DIR" ]; then
    echo "Synthea is not installed."
    echo "Run ./scripts/synthea_loader/scripts/install.sh first."
    exit 1
fi

cd "$SYNTHEA_DIR"

rm -rf output

echo "Generating Synthea population..."
echo "Population: $POPULATION"
echo "Seed:       $SEED"
echo "State:      $STATE"
echo "Ages:       $AGE_RANGE"

./run_synthea \
    -s "$SEED" \
    -p "$POPULATION" \
    -a "$AGE_RANGE" \
    "$STATE"

echo
echo "Generated files:"
find output -maxdepth 3 -type f | sort
