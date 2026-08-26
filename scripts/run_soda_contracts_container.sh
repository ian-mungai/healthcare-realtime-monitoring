#!/usr/bin/env bash

set -euo pipefail

CONFIGURATION="/app/configuration.yml"
CONTRACTS_DIRECTORY="/app/contracts"

for contract in "${CONTRACTS_DIRECTORY}"/*.yml; do
  echo "Testing Soda contract: ${contract}"

  soda contract test \
    --contract "${contract}"

  echo "Verifying Soda contract: ${contract}"

  soda contract verify \
    -ds "${CONFIGURATION}" \
    -c "${contract}"
done

echo "All Soda contracts passed."