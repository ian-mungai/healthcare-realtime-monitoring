#!/usr/bin/env bash

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

SODA_DATA_SOURCE="data_quality/soda/config/configuration.yml"

for contract in data_quality/soda/contracts/*.yml; do
  echo "Testing Soda contract: ${contract}"

  soda contract test \
    --contract "${contract}"

  echo "Verifying Soda contract: ${contract}"

  soda contract verify \
    -ds "${SODA_DATA_SOURCE}" \
    -c "${contract}"
done