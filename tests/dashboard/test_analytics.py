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
        columns = ["patient_id", "encounter_key", "model_version", "deterioration_probability", "proxy_risk_band", "scored_at"]
        return {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": column} for column in columns]},
                "Rows": [
                    {"Data": [{"VarCharValue": column} for column in columns]},
                    {
                        "Data": [
                            {"VarCharValue": "Patient/1000"},
                            {"VarCharValue": "encounter-1"},
                            {"VarCharValue": "logistic-abc123"},
                            {"VarCharValue": "0.25"},
                            {"VarCharValue": "baseline_proxy"},
                            {"VarCharValue": "2026-09-14 12:00:00.000000"},
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
        "healthcare_realtime_dbt", "s3://example-bucket/athena_results/dashboard/", "us-east-1", athena_client=client, poll_interval_seconds=0
    )

    assert records[0]["patient_id"] == "Patient/1000"
    assert "partition by predictions.patient_key" in str(client.query)
    assert "where patient_rank = 1" in str(client.query)


def test_load_latest_predictions_reports_athena_failure() -> None:
    with pytest.raises(RuntimeError, match="test failure"):
        load_latest_predictions(
            "healthcare_realtime_dbt",
            "s3://example-bucket/athena_results/dashboard/",
            "us-east-1",
            athena_client=RecordingAthenaClient("FAILED"),
            poll_interval_seconds=0,
        )


def test_load_latest_predictions_validates_configuration() -> None:
    with pytest.raises(ValueError, match="database"):
        load_latest_predictions("invalid-name", "s3://example-bucket/results/", "us-east-1")
    with pytest.raises(ValueError, match="S3 URI"):
        load_latest_predictions("healthcare_realtime_dbt", "local-results", "us-east-1")
