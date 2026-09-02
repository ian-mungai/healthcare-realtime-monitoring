from __future__ import annotations

import os
import time
from uuid import uuid4

import boto3
from openlineage.client.event_v2 import RunState

from lineage.openlineage.athena_lineage import emit_s3_athena_lineage

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
ATHENA_DATABASE = os.getenv("GLUE_DATABASE", "healthcare_realtime")
ATHENA_TABLE = os.getenv("GLUE_TABLE", "processed_fhir_observations")
ATHENA_OUTPUT = os.getenv("ATHENA_OUTPUT", "s3://imungai-healthcare-realtime/athena_results/")
ATHENA_WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
ATHENA_POLL_INTERVAL_SECONDS = int(os.getenv("ATHENA_POLL_INTERVAL_SECONDS", "5"))
ATHENA_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}

ATHENA_VALIDATION_QUERY = f"""
SELECT COUNT(*) AS invalid_row_count
FROM {ATHENA_DATABASE}.{ATHENA_TABLE}
WHERE observation_id IS NULL
OR patient_id IS NULL
OR patient_id = ''
OR loinc_code IS NULL
OR value IS NULL
OR effective_datetime IS NULL
"""


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


def run_athena_validation() -> str:
    lineage_run_id = str(uuid4())
    emit_athena_lineage_event(RunState.START, lineage_run_id)

    try:
        athena_client = boto3.client("athena", region_name=AWS_REGION)
        response = athena_client.start_query_execution(
            QueryString=ATHENA_VALIDATION_QUERY,
            QueryExecutionContext={"Database": ATHENA_DATABASE},
            ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
            WorkGroup=ATHENA_WORKGROUP,
        )
        query_execution_id = response["QueryExecutionId"]
        status = wait_for_athena_query(athena_client, query_execution_id)

        if status["State"] != "SUCCEEDED":
            reason = status.get("StateChangeReason", "Athena query did not succeed")
            raise RuntimeError(f"Athena validation failed with state {status['State']}: {reason}")

        invalid_row_count = get_invalid_row_count(athena_client, query_execution_id)

        if invalid_row_count > 0:
            raise RuntimeError(f"Processed Iceberg table contains {invalid_row_count} invalid rows")

        emit_athena_lineage_event(RunState.COMPLETE, lineage_run_id)
        return query_execution_id
    except Exception:
        emit_athena_lineage_event(RunState.FAIL, lineage_run_id)
        raise
