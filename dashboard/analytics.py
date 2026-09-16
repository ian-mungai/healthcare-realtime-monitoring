from __future__ import annotations

import re
import time
from typing import Any

import boto3

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _cell_value(cell: dict[str, str]) -> str | None:
    return cell.get("VarCharValue")


def _result_rows(athena_client: Any, query_execution_id: str) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    next_token: str | None = None
    column_names: list[str] = []

    while True:
        request = {"QueryExecutionId": query_execution_id}
        if next_token:
            request["NextToken"] = next_token
        response = athena_client.get_query_results(**request)
        result_set = response["ResultSet"]
        if not column_names:
            column_names = [column["Name"] for column in result_set["ResultSetMetadata"]["ColumnInfo"]]

        for row in result_set.get("Rows", []):
            values = [_cell_value(cell) for cell in row.get("Data", [])]
            values.extend([None] * (len(column_names) - len(values)))
            record = dict(zip(column_names, values, strict=True))
            if list(record.values()) != column_names:
                rows.append(record)

        next_token = response.get("NextToken")
        if not next_token:
            return rows


def load_latest_predictions(
    database: str,
    predictions_table: str,
    patient_table: str,
    encounter_table: str,
    features_table: str,
    output_location: str,
    region: str,
    catalog: str,
    workgroup: str,
    athena_client: Any | None = None,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.5,
) -> list[dict[str, str | None]]:
    for label, identifier in {
        "database": database,
        "predictions table": predictions_table,
        "patient table": patient_table,
        "encounter table": encounter_table,
        "features table": features_table,
        "catalog": catalog,
        "workgroup": workgroup,
    }.items():
        if not IDENTIFIER_PATTERN.fullmatch(identifier):
            raise ValueError(f"Invalid Athena {label}: {identifier}")
    if not output_location.startswith("s3://"):
        raise ValueError("Athena output location must be an S3 URI")

    client = athena_client or boto3.client("athena", region_name=region)
    query = f"""
with ranked as (
    select
        patients.patient_reference as patient_id,
        encounters.encounter_id,
        predictions.encounter_key,
        predictions.model_version,
        predictions.deterioration_probability,
        predictions.predicted_label,
        predictions.decision_threshold,
        predictions.proxy_risk_band,
        predictions.feature_schema_version,
        predictions.label_definition_version,
        predictions.dataset_fingerprint,
        predictions.prediction_scope,
        predictions.is_clinically_validated,
        predictions.scored_at,
        features.feature_observation_count,
        features.heart_rate_mean,
        features.respiratory_rate_mean,
        features.spo2_mean,
        features.systolic_bp_mean,
        features.diastolic_bp_mean,
        row_number() over (
            partition by predictions.patient_key
            order by predictions.scored_at desc, predictions.encounter_key desc
        ) as patient_rank
    from {database}.{predictions_table} as predictions
    inner join {database}.{patient_table} as patients
        on predictions.patient_key = patients.patient_key
    inner join {database}.{encounter_table} as encounters
        on predictions.encounter_key = encounters.encounter_key
    left join {database}.{features_table} as features
        on predictions.encounter_key = features.encounter_key
)
select
    patient_id,
    encounter_id,
    encounter_key,
    model_version,
    deterioration_probability,
    predicted_label,
    decision_threshold,
    proxy_risk_band,
    feature_schema_version,
    label_definition_version,
    dataset_fingerprint,
    prediction_scope,
    is_clinically_validated,
    scored_at,
    feature_observation_count,
    heart_rate_mean,
    respiratory_rate_mean,
    spo2_mean,
    systolic_bp_mean,
    diastolic_bp_mean
from ranked
where patient_rank = 1
order by deterioration_probability desc, patient_id
""".strip()
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database, "Catalog": catalog},
        ResultConfiguration={"OutputLocation": output_location},
        WorkGroup=workgroup,
    )
    query_execution_id = response["QueryExecutionId"]
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        execution = client.get_query_execution(QueryExecutionId=query_execution_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            return _result_rows(client, query_execution_id)
        if state in {"FAILED", "CANCELLED"}:
            reason = execution["Status"].get("StateChangeReason", "No reason returned")
            raise RuntimeError(f"Athena prediction query {state.lower()}: {reason}")
        time.sleep(poll_interval_seconds)

    client.stop_query_execution(QueryExecutionId=query_execution_id)
    raise TimeoutError("Athena prediction query exceeded its time limit")
