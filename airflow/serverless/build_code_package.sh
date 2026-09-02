#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_ROOT="$REPO_ROOT/tmp/mwaa_serverless_code"
PACKAGE_PATH="$REPO_ROOT/tmp/healthcare_realtime_mwaa_serverless_code.zip"

rm -rf "$BUILD_ROOT"
rm -f "$PACKAGE_PATH"

mkdir -p "$BUILD_ROOT/lib"
mkdir -p "$BUILD_ROOT/lineage/openlineage"

cp "$REPO_ROOT/airflow/dags/lib/__init__.py" "$BUILD_ROOT/lib/__init__.py"
cp "$REPO_ROOT/airflow/dags/lib/athena_lineage.py" "$BUILD_ROOT/lib/athena_lineage.py"

cp "$REPO_ROOT/lineage/__init__.py" "$BUILD_ROOT/lineage/__init__.py"
cp "$REPO_ROOT/lineage/openlineage/__init__.py" "$BUILD_ROOT/lineage/openlineage/__init__.py"
cp "$REPO_ROOT/lineage/openlineage/client.py" "$BUILD_ROOT/lineage/openlineage/client.py"
cp "$REPO_ROOT/lineage/openlineage/athena_lineage.py" "$BUILD_ROOT/lineage/openlineage/athena_lineage.py"

python3 -m pip install \
  --requirement "$REPO_ROOT/airflow/serverless/requirements.txt" \
  --target "$BUILD_ROOT" \
  --platform manylinux2014_x86_64 \
  --python-version 3.12 \
  --only-binary=:all:

find "$BUILD_ROOT" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$BUILD_ROOT" -type f -name "*.pyc" -delete

BUILD_ROOT="$BUILD_ROOT" PACKAGE_PATH="$PACKAGE_PATH" python3 - <<'PY'
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

build_root = Path(os.environ["BUILD_ROOT"])
package_path = Path(os.environ["PACKAGE_PATH"])
fixed_timestamp = (1980, 1, 1, 0, 0, 0)

with ZipFile(package_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(p for p in build_root.rglob("*") if p.is_file()):
        relative_path = path.relative_to(build_root).as_posix()

        info = ZipInfo(relative_path, date_time=fixed_timestamp)
        info.compress_type = ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = 0o100644 << 16

        archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
PY

echo "Built MWAA Serverless code package:"
echo "$PACKAGE_PATH"