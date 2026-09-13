from pathlib import Path
from typing import Any

import joblib
import pytest

from jobs.ml.train_logistic_regression import FEATURE_COLUMNS, dataset_fingerprint, evaluate_baseline, load_athena_records, train_baseline, write_artifacts


def training_record(index: int, split: str, label: int) -> dict[str, Any]:
    record: dict[str, Any] = {
        "encounter_key": f"encounter-{index:02d}",
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

    assert dataset_fingerprint(records) == dataset_fingerprint(list(reversed(records)))


def test_train_baseline_is_reproducible() -> None:
    first_model, first_manifest = train_baseline(sample_records())
    second_model, second_manifest = train_baseline(sample_records())

    assert first_manifest == second_manifest
    assert first_manifest["training_row_count"] == 4
    assert first_manifest["test_row_count"] == 2
    assert first_manifest["training_class_counts"] == {"0": 2, "1": 2}
    assert first_model.named_steps["classifier"].coef_.tolist() == second_model.named_steps["classifier"].coef_.tolist()


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

    write_artifacts(model, manifest, tmp_path, evaluation)

    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "evaluation.json").is_file()
    loaded_model = joblib.load(tmp_path / "model.joblib")
    assert loaded_model.predict([[1.0] * len(FEATURE_COLUMNS)]).shape == (1,)


def test_evaluate_baseline_reports_test_metrics_and_training_threshold() -> None:
    model, _ = train_baseline(sample_records())

    evaluation = evaluate_baseline(model, sample_records())

    assert evaluation["evaluation_partition"] == "test"
    assert evaluation["evaluation_row_count"] == 2
    assert evaluation["evaluation_class_counts"] == {"0": 1, "1": 1}
    assert 0.0 <= evaluation["roc_auc"] <= 1.0
    assert evaluation["default_operating_point"]["threshold"] == 0.5
    assert evaluation["threshold_selection"]["partition"] == "train"
    assert sum(evaluation["selected_operating_point"]["confusion_matrix"].values()) == 2


def test_evaluate_baseline_rejects_single_class_test_data() -> None:
    records = sample_records()
    records[-1]["deterioration_proxy_label"] = 0
    model, _ = train_baseline(records)

    with pytest.raises(ValueError, match="Test partition must contain labels 0 and 1"):
        evaluate_baseline(model, records)


def test_athena_loader_rejects_unsafe_identifiers() -> None:
    with pytest.raises(ValueError, match="Invalid Athena identifier"):
        load_athena_records("healthcare_realtime_dbt; drop table x", "ml_training_dataset", "s3://example/results/", "us-east-1")
