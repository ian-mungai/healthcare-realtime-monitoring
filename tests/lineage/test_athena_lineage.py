from unittest.mock import MagicMock, patch

import pytest
from openlineage.client.event_v2 import RunState

from lineage.openlineage.athena_lineage import build_athena_lineage_event
from lineage.openlineage.client import S3Transport
from lineage.openlineage.config import lineage_event_path
from testkit import expect

VALIDATION_ARGUMENTS = {
    "data_bucket_name": "example-data-bucket",
    "aws_region": "example-region-1",
    "database": "example_source",
    "table": "example_processed_observations",
    "workgroup": "example-workgroup",
    "athena_output": "s3://example-data-bucket/athena-results/",
    "project_name": "example-project",
}


def test_athena_lineage_namespace() -> None:
    event = build_athena_lineage_event(RunState.START, "11111111-1111-4111-8111-111111111111")
    expect.equal(event.job.namespace, "example-project")


def test_processed_dataset() -> None:
    event = build_athena_lineage_event(RunState.START, "11111111-1111-4111-8111-111111111111")
    if event.inputs is None:
        expect.fail("expected: event.inputs is not None")
    dataset = event.inputs[0]
    expect.equal(dataset.namespace, "aws-glue")
    expect.equal(dataset.name, "example_source.example_processed_observations")


def test_validation_dataset() -> None:
    event = build_athena_lineage_event(RunState.START, "11111111-1111-4111-8111-111111111111")
    if event.outputs is None:
        expect.fail("expected: event.outputs is not None")
    dataset = event.outputs[0]
    expect.equal(dataset.namespace, "athena")
    expect.equal(dataset.name, "example_source.example_processed_observations_quality")


def test_athena_lineage_s3_path() -> None:
    expect.equal(lineage_event_path("athena"), "s3://example-data-bucket/lineage/openlineage/athena/event")


@patch("lineage.openlineage.client.boto3.client")
def test_s3_transport_writes_openlineage_event(mock_boto_client: MagicMock) -> None:
    s3_client = MagicMock()
    mock_boto_client.return_value = s3_client
    lineage_run_id = "44444444-4444-4444-8444-444444444444"
    event = build_athena_lineage_event(RunState.START, lineage_run_id)

    transport = S3Transport(lineage_event_path("athena"))
    transport.emit(event)

    mock_boto_client.assert_called_once_with("s3")
    s3_client.put_object.assert_called_once()

    call = s3_client.put_object.call_args.kwargs

    expect.equal(call["Bucket"], "example-data-bucket")
    if not call["Key"].startswith("lineage/openlineage/athena/event-"):
        expect.fail('expected: call["Key"].startswith("lineage/openlineage/athena/event-")')
    if not call["Key"].endswith(".json"):
        expect.fail('expected: call["Key"].endswith(".json")')
    expect.equal(call["ContentType"], "application/json")
    expect.is_in(lineage_run_id.encode(), call["Body"])


def test_s3_transport_rejects_invalid_path() -> None:
    with pytest.raises(ValueError, match="Invalid S3 lineage event path"):
        S3Transport("lineage/openlineage/athena/event")


def test_athena_start_complete_lifecycle_uses_same_run_id() -> None:
    lineage_run_id = "11111111-1111-4111-8111-111111111111"

    start_event = build_athena_lineage_event(RunState.START, lineage_run_id)
    complete_event = build_athena_lineage_event(RunState.COMPLETE, lineage_run_id)

    expect.equal(start_event.eventType, RunState.START)
    expect.equal(complete_event.eventType, RunState.COMPLETE)
    expect.equal(start_event.run.runId, lineage_run_id)
    expect.equal(complete_event.run.runId, lineage_run_id)
    expect.equal(start_event.run.runId, complete_event.run.runId)


def test_athena_start_fail_lifecycle_uses_same_run_id() -> None:
    lineage_run_id = "22222222-2222-4222-8222-222222222222"

    start_event = build_athena_lineage_event(RunState.START, lineage_run_id)
    fail_event = build_athena_lineage_event(RunState.FAIL, lineage_run_id)

    expect.equal(start_event.eventType, RunState.START)
    expect.equal(fail_event.eventType, RunState.FAIL)
    expect.equal(start_event.run.runId, lineage_run_id)
    expect.equal(fail_event.run.runId, lineage_run_id)
    expect.equal(start_event.run.runId, fail_event.run.runId)


def test_athena_lifecycle_preserves_datasets() -> None:
    lineage_run_id = "33333333-3333-4333-8333-333333333333"

    event = build_athena_lineage_event(RunState.COMPLETE, lineage_run_id)

    if event.inputs is None:
        expect.fail("expected: event.inputs is not None")
    if event.outputs is None:
        expect.fail("expected: event.outputs is not None")
    expect.equal(event.inputs[0].name, "example_source.example_processed_observations")
    expect.equal(event.outputs[0].name, "example_source.example_processed_observations_quality")


def test_get_invalid_row_count_returns_count() -> None:
    from airflow.dags.lib.athena_lineage import get_invalid_row_count

    athena_client = MagicMock()
    athena_client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "invalid_row_count"}]}, {"Data": [{"VarCharValue": "7"}]}]}
    }

    result = get_invalid_row_count(athena_client, "query-123")

    expect.equal(result, 7)
    athena_client.get_query_results.assert_called_once_with(QueryExecutionId="query-123")


def test_athena_validation_query_checks_compound_grain_uniqueness() -> None:
    from airflow.dags.lib.athena_lineage import validation_query

    normalized_query = " ".join(validation_query("example_source", "example_table").split()).upper()

    expect.is_in("GROUP BY OBSERVATION_ID, LOINC_CODE", normalized_query)
    expect.is_in("HAVING COUNT(*) > 1", normalized_query)
    expect.is_in("SELECT COUNT(*) FROM DUPLICATE_GRAINS", normalized_query)


def test_get_invalid_row_count_rejects_missing_count() -> None:
    from airflow.dags.lib.athena_lineage import get_invalid_row_count

    athena_client = MagicMock()
    athena_client.get_query_results.return_value = {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": "invalid_row_count"}]}]}}

    with pytest.raises(RuntimeError, match="Athena validation query returned no invalid-row count"):
        get_invalid_row_count(athena_client, "query-123")


@patch("airflow.dags.lib.athena_lineage.emit_athena_lineage_event")
@patch("airflow.dags.lib.athena_lineage.boto3.client")
def test_run_athena_validation_emits_start_complete(mock_boto_client: MagicMock, mock_emit: MagicMock) -> None:
    from airflow.dags.lib.athena_lineage import run_athena_validation

    athena_client = MagicMock()
    athena_client.start_query_execution.return_value = {"QueryExecutionId": "query-123"}
    athena_client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    athena_client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "invalid_row_count"}]}, {"Data": [{"VarCharValue": "0"}]}]}
    }
    mock_boto_client.return_value = athena_client

    result = run_athena_validation(**VALIDATION_ARGUMENTS)

    expect.equal(result, "query-123")
    athena_client.get_query_results.assert_called_once_with(QueryExecutionId="query-123")
    expect.equal(mock_emit.call_count, 2)
    expect.equal(mock_emit.call_args_list[0].args[0], RunState.START)
    expect.equal(mock_emit.call_args_list[1].args[0], RunState.COMPLETE)
    expect.equal(mock_emit.call_args_list[0].args[1], mock_emit.call_args_list[1].args[1])


@patch("airflow.dags.lib.athena_lineage.emit_athena_lineage_event")
@patch("airflow.dags.lib.athena_lineage.boto3.client")
def test_run_athena_validation_invalid_rows_emits_start_fail(mock_boto_client: MagicMock, mock_emit: MagicMock) -> None:
    from airflow.dags.lib.athena_lineage import run_athena_validation

    athena_client = MagicMock()
    athena_client.start_query_execution.return_value = {"QueryExecutionId": "query-456"}
    athena_client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    athena_client.get_query_results.return_value = {
        "ResultSet": {"Rows": [{"Data": [{"VarCharValue": "invalid_row_count"}]}, {"Data": [{"VarCharValue": "4"}]}]}
    }
    mock_boto_client.return_value = athena_client

    with pytest.raises(RuntimeError, match="Processed Iceberg table contains 4 quality violations"):
        run_athena_validation(**VALIDATION_ARGUMENTS)

    expect.equal(mock_emit.call_count, 2)
    expect.equal(mock_emit.call_args_list[0].args[0], RunState.START)
    expect.equal(mock_emit.call_args_list[1].args[0], RunState.FAIL)
    expect.equal(mock_emit.call_args_list[0].args[1], mock_emit.call_args_list[1].args[1])


@patch("airflow.dags.lib.athena_lineage.emit_athena_lineage_event")
@patch("airflow.dags.lib.athena_lineage.boto3.client")
def test_run_athena_validation_emits_start_fail(mock_boto_client: MagicMock, mock_emit: MagicMock) -> None:
    from airflow.dags.lib.athena_lineage import run_athena_validation

    athena_client = MagicMock()
    athena_client.start_query_execution.return_value = {"QueryExecutionId": "query-789"}
    athena_client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": "validation error"}}}
    mock_boto_client.return_value = athena_client

    with pytest.raises(RuntimeError, match="validation error"):
        run_athena_validation(**VALIDATION_ARGUMENTS)

    athena_client.get_query_results.assert_not_called()
    expect.equal(mock_emit.call_count, 2)
    expect.equal(mock_emit.call_args_list[0].args[0], RunState.START)
    expect.equal(mock_emit.call_args_list[1].args[0], RunState.FAIL)
    expect.equal(mock_emit.call_args_list[0].args[1], mock_emit.call_args_list[1].args[1])
