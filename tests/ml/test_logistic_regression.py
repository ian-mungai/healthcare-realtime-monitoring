import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pytest

from jobs.ml.train_logistic_regression import (
    FEATURE_COLUMNS,
    SCORING_REQUIRED_COLUMNS,
    build_prediction_records,
    dataset_fingerprint,
    evaluate_baseline,
    load_athena_records,
    prediction_partition_statement,
    publish_artifacts,
    publish_predictions,
    train_baseline,
    validate_scoring_contract,
    write_artifacts,
)
from testkit import expect


def training_record(index: int, split: str, label: int) -> dict[str, Any]:
    record: dict[str, Any] = {
        "encounter_key": f"encounter-{index:02d}",
        "patient_key": f"patient-{index // 2:02d}",
        "data_split": split,
        "feature_schema_version": "vital-features-v1",
        "label_definition_version": "news2-extreme-proxy-v1",
        "deterioration_proxy_label": label,
    }
    record.update({column: float(index + position) for position, column in enumerate(FEATURE_COLUMNS)})
    return record


def sample_records() -> list[dict[str, Any]]:
    return [
        training_record(1, "train", 0),
        training_record(2, "train", 0),
        training_record(3, "train", 1),
        training_record(4, "train", 1),
        training_record(5, "test", 0),
        training_record(6, "test", 1),
    ]


def test_dataset_fingerprint_is_order_independent() -> None:
    records = sample_records()

    expect.equal(dataset_fingerprint(records), dataset_fingerprint(list(reversed(records))))


def test_train_baseline_is_reproducible() -> None:
    first_model, first_manifest = train_baseline(sample_records())
    second_model, second_manifest = train_baseline(sample_records())

    expect.equal(first_manifest, second_manifest)
    expect.equal(first_manifest["training_row_count"], 4)
    expect.equal(first_manifest["test_row_count"], 2)
    expect.equal(first_manifest["training_class_counts"], {"0": 2, "1": 2})
    expect.equal(first_model.named_steps["classifier"].coef_.tolist(), second_model.named_steps["classifier"].coef_.tolist())


def test_train_baseline_rejects_single_class_training_data() -> None:
    records = [training_record(1, "train", 0), training_record(2, "test", 1)]

    with pytest.raises(ValueError, match="labels 0 and 1"):
        train_baseline(records)


def test_train_baseline_rejects_mixed_feature_versions() -> None:
    records = sample_records()
    records[-1]["feature_schema_version"] = "vital-features-v2"

    with pytest.raises(ValueError, match="one feature schema version"):
        train_baseline(records)


def test_write_artifacts_creates_loadable_model_and_manifest(tmp_path: Path) -> None:
    model, manifest = train_baseline(sample_records())
    evaluation = evaluate_baseline(model, sample_records())
    predictions = build_prediction_records(model, sample_records(), manifest, 0.5, datetime(2026, 9, 13, tzinfo=UTC))

    write_artifacts(model, manifest, tmp_path, evaluation, predictions)

    if not (tmp_path / "manifest.json").is_file():
        expect.fail('expected: (tmp_path / "manifest.json").is_file()')
    if not (tmp_path / "evaluation.json").is_file():
        expect.fail('expected: (tmp_path / "evaluation.json").is_file()')
    expect.equal(len((tmp_path / "predictions.jsonl").read_text().splitlines()), len(sample_records()))
    loaded_model = joblib.load(tmp_path / "model.joblib")
    expect.equal(loaded_model.predict([[1.0] * len(FEATURE_COLUMNS)]).shape, (1,))
    persisted_manifest = json.loads((tmp_path / "manifest.json").read_text())
    expect.equal(persisted_manifest["model_sha256"], manifest["model_sha256"])


def test_evaluate_baseline_reports_test_metrics_and_training_threshold() -> None:
    model, _ = train_baseline(sample_records())

    evaluation = evaluate_baseline(model, sample_records())

    expect.equal(evaluation["evaluation_partition"], "test")
    expect.equal(evaluation["evaluation_row_count"], 2)
    expect.equal(evaluation["evaluation_class_counts"], {"0": 1, "1": 1})
    if not (0.0 <= evaluation["roc_auc"] <= 1.0):
        expect.fail('expected: 0.0 <= evaluation["roc_auc"] <= 1.0')
    expect.equal(evaluation["default_operating_point"]["threshold"], 0.5)
    expect.equal(evaluation["threshold_selection"]["partition"], "train")
    expect.equal(sum(evaluation["selected_operating_point"]["confusion_matrix"].values()), 2)


def test_evaluate_baseline_rejects_single_class_test_data() -> None:
    records = sample_records()
    records[-1]["deterioration_proxy_label"] = 0
    model, _ = train_baseline(records)

    with pytest.raises(ValueError, match="Test partition must contain labels 0 and 1"):
        evaluate_baseline(model, records)


def test_prediction_records_include_traceability_and_operating_point() -> None:
    records = sample_records()
    model, manifest = train_baseline(records)

    predictions = build_prediction_records(model, records, manifest, 0.4, datetime(2026, 9, 13, 12, 30, tzinfo=UTC))

    expect.equal(len(predictions), len(records))
    expect.equal(predictions[0]["encounter_key"], records[0]["encounter_key"])
    expect.equal(predictions[0]["patient_key"], records[0]["patient_key"])
    expect.equal(predictions[0]["model_version"], manifest["model_version"])
    expect.equal(predictions[0]["dataset_fingerprint"], dataset_fingerprint(records, SCORING_REQUIRED_COLUMNS))
    expect.equal(predictions[0]["decision_threshold"], 0.4)
    expect.is_in(predictions[0]["predicted_label"], {0, 1})
    if not (0.0 <= predictions[0]["deterioration_probability"] <= 1.0):
        expect.fail('expected: 0.0 <= predictions[0]["deterioration_probability"] <= 1.0')


def test_prediction_records_allow_unlabelled_prospective_features() -> None:
    records = sample_records()
    model, manifest = train_baseline(records)
    scoring_records = [{key: value for key, value in record.items() if key not in {"data_split", "deterioration_proxy_label"}} for record in records]

    predictions = build_prediction_records(model, scoring_records, manifest, 0.4, datetime(2026, 9, 13, 12, 30, tzinfo=UTC))

    expect.identical(predictions[0]["data_split"], None)
    expect.identical(predictions[0]["actual_label"], None)


def test_scoring_contract_rejects_a_model_trained_on_an_old_feature_schema() -> None:
    records = sample_records()
    _, manifest = train_baseline(records)
    scoring_records = [{key: value for key, value in record.items() if key not in {"data_split", "deterioration_proxy_label"}} for record in records]
    scoring_records[0]["feature_schema_version"] = "vital-features-v2"

    with pytest.raises(ValueError, match="feature schema"):
        validate_scoring_contract(scoring_records, manifest)


class RecordingS3Client:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.requests.append(kwargs)


def test_publish_artifacts_uses_versioned_encrypted_paths(tmp_path: Path) -> None:
    for filename in ("model.joblib", "manifest.json", "evaluation.json"):
        (tmp_path / filename).write_text(f"{filename}\n")
    (tmp_path / "predictions.jsonl").write_text('{"model_version":"logistic-abc123"}\n')
    client = RecordingS3Client()

    published = publish_artifacts(tmp_path, "example-bucket", "logistic-abc123", client)

    expect.equal(len(client.requests), 4)
    if not all(request["ServerSideEncryption"] == "AES256" for request in client.requests):
        expect.fail('expected: all(request["ServerSideEncryption"] == "AES256" for request in client.requests)')
    if not all(len(request["Metadata"]["sha256"]) == 64 for request in client.requests):
        expect.fail('expected: all(len(request["Metadata"]["sha256"]) == 64 for request in client.requests)')
    expect.equal(published["model.joblib"], "s3://example-bucket/ml/model_artifacts/logistic-abc123/model.joblib")
    expect.equal(published["predictions.jsonl"], "s3://example-bucket/ml/predictions/model_version=logistic-abc123/predictions.jsonl")


def test_prediction_partition_statement_targets_ml_database() -> None:
    add_partition = prediction_partition_statement("example_ml", "example_predictions", "example-bucket", "logistic-abc123")

    expect.is_in("example_ml.example_predictions", add_partition)
    expect.is_in("model_version = 'logistic-abc123'", add_partition)
    expect.not_in("create external table", add_partition)


def test_published_prediction_lines_exclude_partition_column(tmp_path: Path) -> None:
    model, manifest = train_baseline(sample_records())
    predictions = build_prediction_records(model, sample_records(), manifest, 0.5, datetime(2026, 9, 13, tzinfo=UTC))
    write_artifacts(model, manifest, tmp_path, predictions=predictions)

    client = RecordingS3Client()
    publish_predictions(tmp_path / "predictions.jsonl", "example-bucket", manifest["model_version"], client)

    persisted = json.loads(client.requests[0]["Body"].decode().splitlines()[0])
    expect.not_in("model_version", persisted)


def test_athena_loader_rejects_unsafe_identifiers() -> None:
    with pytest.raises(ValueError, match="Invalid Athena identifier"):
        load_athena_records("healthcare_realtime_dbt; drop table x", "ml_training_dataset", "s3://example/results/", "example-region-1")
