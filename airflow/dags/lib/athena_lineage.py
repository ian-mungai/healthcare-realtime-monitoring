from __future__ import annotations

import os
import time
from uuid import uuid4

import boto3
from openlineage.client.event_v2 import RunState

from lineage.openlineage.athena_lineage import emit_s3_athena_lineage

ATHENA_POLL_INTERVAL_SECONDS = int(os.getenv("ATHENA_POLL_INTERVAL_SECONDS", "5"))
ATHENA_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def validation_query(database: str, table: str) -> str:
    return f"""
    WITH invalid_rows AS (
        SELECT 1 AS violation
        FROM {database}.{table}
        WHERE observation_id IS NULL
        OR patient_id IS NULL
        OR patient_id = ''
        OR loinc_code IS NULL
        OR value IS NULL
        OR effective_datetime IS NULL
    ),
    duplicate_grains AS (
        SELECT observation_id, loinc_code
        FROM {database}.{table}
        WHERE observation_id IS NOT NULL
        AND loinc_code IS NOT NULL
        GROUP BY observation_id, loinc_code
        HAVING COUNT(*) > 1
    )
    SELECT
        (SELECT COUNT(*) FROM invalid_rows)
        + (SELECT COUNT(*) FROM duplicate_grains) AS invalid_row_count
    """.strip()


def emit_athena_lineage_event(run_state: RunState, lineage_run_id: str | None = None) -> str:
    return emit_s3_athena_lineage(run_state, lineage_run_id)


def wait_for_athena_query(athena_client, query_execution_id: str) -> dict:
    while True:
        response = athena_client.get_query_execution(QueryExecutionId=query_execution_id)
        status = response["QueryExecution"]["Status"]

        if status["State"] in ATHENA_TERMINAL_STATES:
            return status

        time.sleep(ATHENA_POLL_INTERVAL_SECONDS)


def get_invalid_row_count(athena_client, query_execution_id: str) -> int:
    response = athena_client.get_query_results(QueryExecutionId=query_execution_id)
    rows = response["ResultSet"]["Rows"]

    if len(rows) < 2 or not rows[1].get("Data") or "VarCharValue" not in rows[1]["Data"][0]:
        raise RuntimeError("Athena validation query returned no invalid-row count")

    return int(rows[1]["Data"][0]["VarCharValue"])


def run_athena_validation(
    data_bucket_name: str,
    aws_region: str,
    database: str,
    table: str,
    workgroup: str,
    athena_output: str,
    project_name: str,
    openlineage_url: str = "",
) -> str:
    os.environ["DATA_BUCKET_NAME"] = data_bucket_name
    os.environ["PROJECT_NAME"] = project_name
    os.environ["ATHENA_SOURCE_DATABASE"] = database
    os.environ["ATHENA_PROCESSED_TABLE"] = table
    if openlineage_url:
        os.environ["OPENLINEAGE_URL"] = openlineage_url
    lineage_run_id = str(uuid4())
    emit_athena_lineage_event(RunState.START, lineage_run_id)

    try:
        athena_client = boto3.client("athena", region_name=aws_region)
        response = athena_client.start_query_execution(
            QueryString=validation_query(database, table),
            QueryExecutionContext={"Database": database},
            ResultConfiguration={"OutputLocation": athena_output},
            WorkGroup=workgroup,
        )
        query_execution_id = response["QueryExecutionId"]
        status = wait_for_athena_query(athena_client, query_execution_id)

        if status["State"] != "SUCCEEDED":
            reason = status.get("StateChangeReason", "Athena query did not succeed")
            raise RuntimeError(f"Athena validation failed with state {status['State']}: {reason}")

        invalid_row_count = get_invalid_row_count(athena_client, query_execution_id)

        if invalid_row_count > 0:
            raise RuntimeError(f"Processed Iceberg table contains {invalid_row_count} quality violations")

        emit_athena_lineage_event(RunState.COMPLETE, lineage_run_id)
        return query_execution_id
    except Exception:
        emit_athena_lineage_event(RunState.FAIL, lineage_run_id)
        raise
