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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import boto3
import joblib
from pyathena import connect
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, roc_auc_score, roc_curve
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
REQUIRED_COLUMNS: Final = ("encounter_key", "patient_key", "data_split", "feature_schema_version", "label_definition_version", TARGET_COLUMN, *FEATURE_COLUMNS)
IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MODEL_VERSION_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RANDOM_STATE: Final = 42
DEFAULT_DECISION_THRESHOLD: Final = 0.5


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


def _features_and_labels(records: list[dict[str, Any]]) -> tuple[list[list[float]], list[int]]:
    features = [[_numeric_value(record[column]) for column in FEATURE_COLUMNS] for record in records]
    labels = [int(record[TARGET_COLUMN]) for record in records]
    return features, labels


def _operating_point(labels: list[int], probabilities: list[float], threshold: float) -> dict[str, Any]:
    predictions = [int(probability >= threshold) for probability in probabilities]
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    sensitivity = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return {
        "threshold": threshold,
        "sensitivity": sensitivity,
        "specificity": specificity,
        "balanced_accuracy": (sensitivity + specificity) / 2,
        "confusion_matrix": {"true_negative": int(tn), "false_positive": int(fp), "false_negative": int(fn), "true_positive": int(tp)},
    }


def _youden_threshold(labels: list[int], probabilities: list[float]) -> float:
    false_positive_rates, true_positive_rates, thresholds = roc_curve(labels, probabilities)
    candidates = [
        (float(true_positive_rate - false_positive_rate), abs(float(threshold) - DEFAULT_DECISION_THRESHOLD), float(threshold))
        for false_positive_rate, true_positive_rate, threshold in zip(false_positive_rates, true_positive_rates, thresholds, strict=True)
        if math.isfinite(threshold) and 0.0 <= threshold <= 1.0
    ]
    return min(candidates, key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))[2]


def evaluate_baseline(model: Pipeline, records: list[dict[str, Any]]) -> dict[str, Any]:
    _validate_records(records)
    training_records = [record for record in records if record["data_split"] == "train"]
    test_records = [record for record in records if record["data_split"] == "test"]
    if not test_records:
        raise ValueError("Test partition is empty")

    training_features, training_labels = _features_and_labels(training_records)
    test_features, test_labels = _features_and_labels(test_records)
    if set(test_labels) != {0, 1}:
        raise ValueError("Test partition must contain labels 0 and 1")

    training_probabilities = model.predict_proba(training_features)[:, 1].tolist()
    test_probabilities = model.predict_proba(test_features)[:, 1].tolist()
    selected_threshold = _youden_threshold(training_labels, training_probabilities)
    return {
        "evaluation_partition": "test",
        "evaluation_row_count": len(test_records),
        "evaluation_class_counts": {str(label): count for label, count in sorted(Counter(test_labels).items())},
        "roc_auc": float(roc_auc_score(test_labels, test_probabilities)),
        "default_operating_point": _operating_point(test_labels, test_probabilities, DEFAULT_DECISION_THRESHOLD),
        "selected_operating_point": _operating_point(test_labels, test_probabilities, selected_threshold),
        "threshold_selection": {
            "strategy": "maximum_youden_j",
            "partition": "train",
            "note": "Exploratory threshold selected on training data; independent validation is required before clinical use.",
        },
    }


def build_prediction_records(
    model: Pipeline, records: list[dict[str, Any]], manifest: dict[str, Any], threshold: float, scored_at: datetime
) -> list[dict[str, Any]]:
    features, _ = _features_and_labels(records)
    probabilities = model.predict_proba(features)[:, 1].tolist()
    timestamp = scored_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    scoring_fingerprint = dataset_fingerprint(records)
    return [
        {
            "model_version": manifest["model_version"],
            "encounter_key": str(record["encounter_key"]),
            "patient_key": str(record["patient_key"]),
            "data_split": str(record["data_split"]),
            "actual_label": int(record[TARGET_COLUMN]),
            "deterioration_probability": float(probability),
            "predicted_label": int(probability >= threshold),
            "decision_threshold": threshold,
            "feature_schema_version": str(record["feature_schema_version"]),
            "label_definition_version": str(record["label_definition_version"]),
            "dataset_fingerprint": scoring_fingerprint,
            "scored_at": timestamp,
        }
        for record, probability in zip(records, probabilities, strict=True)
    ]


def write_artifacts(
    model: Pipeline, manifest: dict[str, Any], output_dir: Path, evaluation: dict[str, Any] | None = None, predictions: list[dict[str, Any]] | None = None
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.joblib"
    joblib.dump(model, model_path)
    manifest["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if evaluation is not None:
        (output_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2, sort_keys=True) + "\n")
    if predictions is not None:
        content = "".join(json.dumps(record, sort_keys=True) + "\n" for record in predictions)
        (output_dir / "predictions.jsonl").write_text(content)


def _s3_location(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 URI: {uri}")
    return parsed.netloc, parsed.path.strip("/")


def publish_artifacts(output_dir: Path, bucket: str, model_version: str, s3_client: Any | None = None) -> dict[str, str]:
    if not MODEL_VERSION_PATTERN.fullmatch(model_version):
        raise ValueError(f"Invalid model version: {model_version}")
    client = s3_client or boto3.client("s3")
    published: dict[str, str] = {}
    content_types = {"model.joblib": "application/octet-stream", "manifest.json": "application/json", "evaluation.json": "application/json"}
    for filename, content_type in content_types.items():
        path = output_dir / filename
        body = path.read_bytes()
        key = f"ml/model_artifacts/{model_version}/{filename}"
        checksum = hashlib.sha256(body).hexdigest()
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type, ServerSideEncryption="AES256", Metadata={"sha256": checksum})
        published[filename] = f"s3://{bucket}/{key}"

    published["predictions.jsonl"] = publish_predictions(output_dir / "predictions.jsonl", bucket, model_version, client)
    return published


def publish_predictions(predictions_path: Path, bucket: str, model_version: str, s3_client: Any | None = None) -> str:
    if not MODEL_VERSION_PATTERN.fullmatch(model_version):
        raise ValueError(f"Invalid model version: {model_version}")
    client = s3_client or boto3.client("s3")
    records = [json.loads(line) for line in predictions_path.read_text().splitlines() if line]
    for record in records:
        if record.pop("model_version", model_version) != model_version:
            raise ValueError("Prediction model version does not match the S3 partition")
    body = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records).encode()
    key = f"ml/predictions/model_version={model_version}/predictions.jsonl"
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/x-ndjson",
        ServerSideEncryption="AES256",
        Metadata={"sha256": hashlib.sha256(body).hexdigest()},
    )
    return f"s3://{bucket}/{key}"


def prediction_table_statements(database: str, bucket: str, model_version: str) -> tuple[str, str]:
    if not IDENTIFIER_PATTERN.fullmatch(database):
        raise ValueError(f"Invalid Athena identifier: {database}")
    if not MODEL_VERSION_PATTERN.fullmatch(model_version):
        raise ValueError(f"Invalid model version: {model_version}")
    table_location = f"s3://{bucket}/ml/predictions/"
    partition_location = f"{table_location}model_version={model_version}/"
    create_table = f"""
create external table if not exists {database}.ml_predictions_published (
    encounter_key string,
    patient_key string,
    data_split string,
    actual_label int,
    deterioration_probability double,
    predicted_label int,
    decision_threshold double,
    feature_schema_version string,
    label_definition_version string,
    dataset_fingerprint string,
    scored_at timestamp
)
partitioned by (model_version string)
row format serde 'org.openx.data.jsonserde.JsonSerDe'
location '{table_location}'
""".strip()
    add_partition = f"""
alter table {database}.ml_predictions_published
add if not exists partition (model_version = '{model_version}')
location '{partition_location}'
""".strip()
    return create_table, add_partition


def register_predictions_table(database: str, staging_dir: str, region: str, bucket: str, model_version: str) -> None:
    statements = prediction_table_statements(database, bucket, model_version)
    with connect(s3_staging_dir=staging_dir, region_name=region).cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, help="Local export of the dbt training dataset")
    parser.add_argument("--athena-database", default="healthcare_realtime_dbt")
    parser.add_argument("--athena-table", default="ml_training_dataset")
    parser.add_argument("--athena-staging-dir", help="S3 URI for Athena query results")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--output-dir", type=Path, default=Path("build/ml/logistic_baseline"))
    parser.add_argument("--publish-s3", action="store_true", help="Publish versioned artifacts and predictions to the project bucket")
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
    evaluation = evaluate_baseline(model, records)
    manifest["evaluation"] = {"roc_auc": evaluation["roc_auc"], "selected_threshold": evaluation["selected_operating_point"]["threshold"]}
    predictions = build_prediction_records(model, records, manifest, evaluation["selected_operating_point"]["threshold"], datetime.now(UTC))
    write_artifacts(model, manifest, args.output_dir, evaluation, predictions)

    published = None
    if args.publish_s3:
        bucket = os.getenv("DATA_BUCKET_NAME")
        if not bucket:
            raise SystemExit("Set DATA_BUCKET_NAME before using --publish-s3")
        published = publish_artifacts(args.output_dir, bucket, manifest["model_version"])
        register_predictions_table(args.athena_database, staging_dir, args.region, bucket, manifest["model_version"])

    print(json.dumps({"manifest": manifest, "evaluation": evaluation, "published": published}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
