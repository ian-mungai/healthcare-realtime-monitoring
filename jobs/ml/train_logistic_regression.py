"""Train a reproducible logistic-regression baseline from encounter features."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Final

import joblib
from pyathena import connect
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS: Final = (
    "heart_rate_mean",
    "heart_rate_min",
    "heart_rate_max",
    "heart_rate_stddev",
    "respiratory_rate_mean",
    "respiratory_rate_min",
    "respiratory_rate_max",
    "spo2_mean",
    "spo2_min",
    "systolic_bp_mean",
    "systolic_bp_min",
    "diastolic_bp_mean",
)
TARGET_COLUMN: Final = "deterioration_proxy_label"
REQUIRED_COLUMNS: Final = ("encounter_key", "data_split", "feature_schema_version", "label_definition_version", TARGET_COLUMN, *FEATURE_COLUMNS)
IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RANDOM_STATE: Final = 42


def load_csv_records(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_athena_records(database: str, table: str, staging_dir: str, region: str) -> list[dict[str, Any]]:
    for identifier in (database, table):
        if not IDENTIFIER_PATTERN.fullmatch(identifier):
            raise ValueError(f"Invalid Athena identifier: {identifier}")

    columns = ", ".join(REQUIRED_COLUMNS)
    query = f"select {columns} from {database}.{table} order by encounter_key"
    with connect(s3_staging_dir=staging_dir, region_name=region).cursor() as cursor:
        cursor.execute(query)
        names = [description[0] for description in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _numeric_value(value: Any) -> float:
    if value is None or str(value).strip() == "":
        return math.nan
    return float(value)


def _validate_records(records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError("Training dataset is empty")
    missing = [column for column in REQUIRED_COLUMNS if column not in records[0]]
    if missing:
        raise ValueError(f"Training dataset is missing columns: {', '.join(missing)}")
    if {str(record["data_split"]) for record in records} != {"train", "test"}:
        raise ValueError("Training dataset must contain only train and test partitions")
    if len({str(record["feature_schema_version"]) for record in records}) != 1:
        raise ValueError("Training dataset must contain one feature schema version")
    if len({str(record["label_definition_version"]) for record in records}) != 1:
        raise ValueError("Training dataset must contain one label definition version")


def dataset_fingerprint(records: list[dict[str, Any]]) -> str:
    fingerprint_columns = REQUIRED_COLUMNS
    normalized = [[str(record.get(column, "")) for column in fingerprint_columns] for record in sorted(records, key=lambda row: str(row["encounter_key"]))]
    payload = json.dumps(normalized, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def train_baseline(records: list[dict[str, Any]]) -> tuple[Pipeline, dict[str, Any]]:
    _validate_records(records)
    training_records = [record for record in records if record["data_split"] == "train"]
    if not training_records:
        raise ValueError("Training partition is empty")

    features = [[_numeric_value(record[column]) for column in FEATURE_COLUMNS] for record in training_records]
    labels = [int(record[TARGET_COLUMN]) for record in training_records]
    class_counts = Counter(labels)
    if set(class_counts) != {0, 1}:
        raise ValueError("Training partition must contain labels 0 and 1")

    model = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE, solver="liblinear")),
        ]
    )
    model.fit(features, labels)

    fingerprint = dataset_fingerprint(records)
    manifest = {
        "model_type": "logistic_regression",
        "model_version": f"logistic-{fingerprint[:12]}",
        "dataset_fingerprint": fingerprint,
        "feature_columns": list(FEATURE_COLUMNS),
        "target_column": TARGET_COLUMN,
        "feature_schema_versions": sorted({str(record["feature_schema_version"]) for record in records}),
        "label_definition_versions": sorted({str(record["label_definition_version"]) for record in records}),
        "split_strategy": "patient_key_md5_bucket_0_to_7_train_8_to_9_test",
        "random_state": RANDOM_STATE,
        "training_row_count": len(training_records),
        "test_row_count": sum(record["data_split"] == "test" for record in records),
        "training_class_counts": {str(label): count for label, count in sorted(class_counts.items())},
    }
    return model, manifest


def write_artifacts(model: Pipeline, manifest: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output_dir / "model.joblib")
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, help="Local export of the dbt training dataset")
    parser.add_argument("--athena-database", default="healthcare_realtime_dbt")
    parser.add_argument("--athena-table", default="ml_training_dataset")
    parser.add_argument("--athena-staging-dir", help="S3 URI for Athena query results")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--output-dir", type=Path, default=Path("build/ml/logistic_baseline"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.input_csv:
        records = load_csv_records(args.input_csv)
    else:
        staging_dir = args.athena_staging_dir
        if not staging_dir:
            bucket = os.getenv("DATA_BUCKET_NAME")
            if not bucket:
                raise SystemExit("Set DATA_BUCKET_NAME or pass --athena-staging-dir")
            staging_dir = f"s3://{bucket}/athena_results/ml_training/"
        records = load_athena_records(args.athena_database, args.athena_table, staging_dir, args.region)

    model, manifest = train_baseline(records)
    write_artifacts(model, manifest, args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
