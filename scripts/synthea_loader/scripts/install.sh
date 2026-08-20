#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOADER_DIR="$(dirname "$SCRIPT_DIR")"
SYNTHEA_DIR="$LOADER_DIR/synthea"
VERSION_FILE="$LOADER_DIR/synthea_version.txt"

if [ ! -f "$VERSION_FILE" ]; then
    echo "Missing Synthea version file: $VERSION_FILE"
    exit 1
fi

SYNTHEA_REF="$(tr -d '[:space:]' < "$VERSION_FILE")"

if [ -z "$SYNTHEA_REF" ]; then
    echo "Synthea version cannot be empty."
    exit 1
fi

echo "Synthea ref: $SYNTHEA_REF"

if [ -d "$SYNTHEA_DIR/.git" ]; then
    echo "Synthea checkout already exists."
else
    echo "Cloning Synthea..."

    git clone --depth 1 https://github.com/synthetichealth/synthea.git "$SYNTHEA_DIR"

    cd "$SYNTHEA_DIR"

    if [ "$SYNTHEA_REF" != "master" ]; then
        git fetch --depth 1 origin "$SYNTHEA_REF"
        git checkout FETCH_HEAD
    fi
fi

cd "$SYNTHEA_DIR"

if [ -f ".ci_build_complete" ]; then
    echo "Cached Synthea build found."
    echo "Skipping Gradle build."
    exit 0
fi

echo "Building Synthea..."

./gradlew assemble --build-cache --no-daemon

touch .ci_build_complete

echo "Synthea build complete."