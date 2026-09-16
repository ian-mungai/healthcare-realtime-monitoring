from __future__ import annotations

from typing import Any

import pytest

from dashboard.analytics import load_latest_predictions


class RecordingAthenaClient:
    def __init__(self, state: str = "SUCCEEDED") -> None:
        self.state = state
        self.query: str | None = None

    def start_query_execution(self, **request: Any) -> dict[str, str]:
        self.query = request["QueryString"]
        assert request["ResultConfiguration"]["OutputLocation"] == "s3://example-bucket/athena_results/dashboard/"
        return {"QueryExecutionId": "query-1"}

    def get_query_execution(self, **request: Any) -> dict[str, Any]:
        return {"QueryExecution": {"Status": {"State": self.state, "StateChangeReason": "test failure"}}}

    def get_query_results(self, **request: Any) -> dict[str, Any]:
        columns = [
            "patient_id",
            "encounter_id",
            "encounter_key",
            "model_version",
            "deterioration_probability",
            "predicted_label",
            "decision_threshold",
            "proxy_risk_band",
            "feature_schema_version",
            "label_definition_version",
            "dataset_fingerprint",
            "prediction_scope",
            "is_clinically_validated",
            "scored_at",
            "feature_observation_count",
            "heart_rate_mean",
            "respiratory_rate_mean",
            "spo2_mean",
            "systolic_bp_mean",
            "diastolic_bp_mean",
        ]
        return {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": column} for column in columns]},
                "Rows": [
                    {"Data": [{"VarCharValue": column} for column in columns]},
                    {
                        "Data": [
                            {"VarCharValue": "Patient/1000"},
                            {"VarCharValue": "encounter-1000"},
                            {"VarCharValue": "encounter-1"},
                            {"VarCharValue": "logistic-abc123"},
                            {"VarCharValue": "0.25"},
                            {"VarCharValue": "0"},
                            {"VarCharValue": "0.5"},
                            {"VarCharValue": "baseline_proxy"},
                            {"VarCharValue": "vital-features-v2"},
                            {"VarCharValue": "news2-repeated-extreme-proxy-v2"},
                            {"VarCharValue": "fingerprint-1"},
                            {"VarCharValue": "synthetic_portfolio_only"},
                            {"VarCharValue": "false"},
                            {"VarCharValue": "2026-09-14 12:00:00.000000"},
                            {"VarCharValue": "60"},
                            {"VarCharValue": "82"},
                            {"VarCharValue": "18"},
                            {"VarCharValue": "98"},
                            {"VarCharValue": "119"},
                            {"VarCharValue": "73"},
                        ]
                    },
                ],
            }
        }

    def stop_query_execution(self, **request: Any) -> None:
        pass


def test_load_latest_predictions_returns_one_ranked_row_per_patient() -> None:
    client = RecordingAthenaClient()
    records = load_latest_predictions(
        "example_dbt",
        "example_predictions_latest",
        "example_dim_patient",
        "example_dim_encounter",
        "example_features",
        "s3://example-bucket/athena_results/dashboard/",
        "example-region-1",
        "example_catalog",
        "example_workgroup",
        athena_client=client,
        poll_interval_seconds=0,
    )

    assert records[0]["patient_id"] == "Patient/1000"
    assert "partition by predictions.patient_key" in str(client.query)
    assert "where patient_rank = 1" in str(client.query)
    assert "example_dim_encounter" in str(client.query)
    assert "example_features" in str(client.query)


def test_load_latest_predictions_reports_athena_failure() -> None:
    with pytest.raises(RuntimeError, match="test failure"):
        load_latest_predictions(
            "example_dbt",
            "example_predictions_latest",
            "example_dim_patient",
            "example_dim_encounter",
            "example_features",
            "s3://example-bucket/athena_results/dashboard/",
            "example-region-1",
            "example_catalog",
            "example_workgroup",
            athena_client=RecordingAthenaClient("FAILED"),
            poll_interval_seconds=0,
        )


def test_load_latest_predictions_validates_configuration() -> None:
    with pytest.raises(ValueError, match="database"):
        load_latest_predictions(
            "invalid-name", "predictions", "patients", "encounters", "features", "s3://example-bucket/results/", "example-region-1", "catalog", "workgroup"
        )
    with pytest.raises(ValueError, match="S3 URI"):
        load_latest_predictions("database", "predictions", "patients", "encounters", "features", "local-results", "example-region-1", "catalog", "workgroup")
