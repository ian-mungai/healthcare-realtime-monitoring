"""Score encounter features with an explicitly selected published model."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import joblib
from sklearn.pipeline import Pipeline

from jobs.ml.train_logistic_regression import (
    FEATURE_COLUMNS,
    _s3_location,
    build_prediction_records,
    load_athena_records,
    publish_predictions,
    register_predictions_table,
)


def _verified_body(response: dict[str, Any], name: str) -> bytes:
    body = response["Body"].read()
    expected_checksum = response.get("Metadata", {}).get("sha256")
    if not expected_checksum:
        raise ValueError(f"Published {name} is missing its SHA-256 metadata")
    if hashlib.sha256(body).hexdigest() != expected_checksum:
        raise ValueError(f"Published {name} failed SHA-256 verification")
    return body


def load_published_model(model_s3_uri: str, s3_client: Any | None = None) -> tuple[Pipeline, dict[str, Any]]:
    bucket, prefix = _s3_location(model_s3_uri)
    model_version = prefix.rstrip("/").split("/")[-1]
    client = s3_client or boto3.client("s3")
    manifest_response = client.get_object(Bucket=bucket, Key=f"{prefix.rstrip('/')}/manifest.json")
    model_response = client.get_object(Bucket=bucket, Key=f"{prefix.rstrip('/')}/model.joblib")
    manifest = json.loads(_verified_body(manifest_response, "manifest"))
    if manifest.get("model_version") != model_version:
        raise ValueError("Manifest model version does not match the selected S3 prefix")
    if manifest.get("feature_columns") != list(FEATURE_COLUMNS):
        raise ValueError("Published model feature order does not match the scoring contract")
    if "selected_threshold" not in manifest.get("evaluation", {}):
        raise ValueError("Published model manifest does not contain an evaluated threshold")
    model_body = _verified_body(model_response, "model")
    if hashlib.sha256(model_body).hexdigest() != manifest.get("model_sha256"):
        raise ValueError("Published model checksum does not match its manifest")
    model = joblib.load(io.BytesIO(model_body))
    return model, manifest


def write_predictions(predictions: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in predictions))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-s3-uri", required=True, help="Exact ml/model_artifacts/<model-version> S3 URI selected for scoring")
    parser.add_argument("--athena-database", default="healthcare_realtime_dbt")
    parser.add_argument("--athena-table", default="ml_training_dataset")
    parser.add_argument("--athena-staging-dir", help="S3 URI for Athena query results")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--output", type=Path, default=Path("build/ml/scoring/predictions.jsonl"))
    parser.add_argument("--publish-s3", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bucket = os.getenv("DATA_BUCKET_NAME")
    staging_dir = args.athena_staging_dir or (f"s3://{bucket}/athena_results/ml_scoring/" if bucket else None)
    if not staging_dir:
        raise SystemExit("Set DATA_BUCKET_NAME or pass --athena-staging-dir")

    model, manifest = load_published_model(args.model_s3_uri)
    records = load_athena_records(args.athena_database, args.athena_table, staging_dir, args.region)
    threshold = float(manifest["evaluation"]["selected_threshold"])
    predictions = build_prediction_records(model, records, manifest, threshold, datetime.now(UTC))
    write_predictions(predictions, args.output)

    published = None
    if args.publish_s3:
        if not bucket:
            raise SystemExit("Set DATA_BUCKET_NAME before using --publish-s3")
        published = publish_predictions(args.output, bucket, manifest["model_version"])
        register_predictions_table(args.athena_database, staging_dir, args.region, bucket, manifest["model_version"])
    print(json.dumps({"model_version": manifest["model_version"], "prediction_count": len(predictions), "published": published}, indent=2))


if __name__ == "__main__":
    main()
