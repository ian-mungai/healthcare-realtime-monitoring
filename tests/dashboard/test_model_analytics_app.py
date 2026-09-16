from __future__ import annotations

from datetime import UTC
from typing import Any

import pandas as pd

from dashboard import model_analytics_app


def test_get_model_predictions_uses_environment_configuration(monkeypatch) -> None:
    values = {
        "AWS_REGION": "example-region-1",
        "ATHENA_CATALOG": "example_catalog",
        "ATHENA_WORKGROUP": "example_workgroup",
        "ATHENA_DBT_DATABASE": "example_database",
        "DBT_ML_PREDICTIONS_LATEST_TABLE": "example_predictions",
        "DBT_DIM_PATIENT_TABLE": "example_patients",
        "DBT_DIM_ENCOUNTER_TABLE": "example_encounters",
        "DBT_ENCOUNTER_FEATURES_TABLE": "example_features",
        "ATHENA_RESULTS_S3_URI": "s3://example-bucket/results/",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    loader_calls: list[dict[str, Any]] = []

    def record_loader(**kwargs: Any) -> list[dict[str, str | None]]:
        loader_calls.append(kwargs)
        return []

    monkeypatch.setattr(model_analytics_app, "load_latest_predictions", record_loader)

    model_analytics_app.get_model_predictions.clear()
    assert model_analytics_app.get_model_predictions() == []
    assert loader_calls == [
        {
            "database": "example_database",
            "predictions_table": "example_predictions",
            "patient_table": "example_patients",
            "encounter_table": "example_encounters",
            "features_table": "example_features",
            "output_location": "s3://example-bucket/results/",
            "region": "example-region-1",
            "catalog": "example_catalog",
            "workgroup": "example_workgroup",
        }
    ]


def test_get_model_predictions_reports_missing_configuration(monkeypatch) -> None:
    for name in (
        "AWS_REGION",
        "ATHENA_CATALOG",
        "ATHENA_WORKGROUP",
        "ATHENA_DBT_DATABASE",
        "DBT_ML_PREDICTIONS_LATEST_TABLE",
        "DBT_DIM_PATIENT_TABLE",
        "DBT_DIM_ENCOUNTER_TABLE",
        "DBT_ENCOUNTER_FEATURES_TABLE",
        "ATHENA_RESULTS_S3_URI",
    ):
        monkeypatch.delenv(name, raising=False)

    model_analytics_app.get_model_predictions.clear()
    try:
        model_analytics_app.get_model_predictions()
    except ValueError as error:
        assert "AWS_REGION" in str(error)
        assert "ATHENA_RESULTS_S3_URI" in str(error)
    else:
        raise AssertionError("Missing model analytics configuration should fail")


def test_format_scored_at_uses_local_timezone() -> None:
    timestamp = pd.Timestamp("2026-09-16T12:00:00Z")
    formatted = model_analytics_app.format_scored_at(timestamp)

    assert formatted.startswith("2026-09-16")
    assert model_analytics_app.format_scored_at_compact(timestamp).startswith("Sep 16")
    assert timestamp.tzinfo == UTC


def test_prepare_predictions_adds_readable_labels_and_numeric_features() -> None:
    dataframe = model_analytics_app.prepare_predictions(
        [
            {
                "patient_id": "Patient/1000",
                "encounter_id": "encounter-1000",
                "deterioration_probability": "0.825",
                "decision_threshold": "0.5",
                "proxy_risk_band": "elevated_proxy",
                "scored_at": "2026-09-16T12:00:00Z",
                "feature_observation_count": "60",
                "heart_rate_mean": "82.5",
                "respiratory_rate_mean": "18",
                "spo2_mean": "98",
                "systolic_bp_mean": "119",
                "diastolic_bp_mean": "73",
            }
        ]
    )

    assert dataframe.iloc[0]["patient_id"] == "1000"
    assert dataframe.iloc[0]["risk_label"] == "Elevated proxy"
    assert dataframe.iloc[0]["probability_label"] == "82.5%"
    assert dataframe.iloc[0]["heart_rate_mean"] == 82.5


def test_clinical_validation_values_are_parsed_explicitly() -> None:
    assert model_analytics_app.is_clinically_validated("true")
    assert model_analytics_app.is_clinically_validated(1)
    assert not model_analytics_app.is_clinically_validated("false")


def test_probability_labels_keep_small_values_readable() -> None:
    assert model_analytics_app.format_probability(0.825) == "82.5%"
    assert model_analytics_app.format_probability(0.00001) == "<0.1%"
