from unittest.mock import MagicMock, patch

import pytest
from openlineage.client.event_v2 import RunState

from lineage.openlineage.athena_lineage import NAMESPACE, PROCESSED_DATASET, S3_LINEAGE_EVENT_PATH, VALIDATION_DATASET, build_athena_lineage_event
from lineage.openlineage.client import S3Transport


def test_athena_lineage_namespace() -> None:
    assert NAMESPACE == "healthcare-realtime-monitoring"


def test_processed_dataset() -> None:
    assert PROCESSED_DATASET.namespace == "aws-glue"
    assert PROCESSED_DATASET.name == "healthcare_realtime.processed_fhir_observations"


def test_validation_dataset() -> None:
    assert VALIDATION_DATASET.namespace == "athena"
    assert VALIDATION_DATASET.name == "healthcare_realtime.processed_fhir_observations_quality"


def test_athena_lineage_s3_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://imungai-healthcare-realtime/lineage/openlineage/athena/event"


@patch("lineage.openlineage.client.boto3.client")
def test_s3_transport_writes_openlineage_event(mock_boto_client: MagicMock) -> None:
    s3_client = MagicMock()
    mock_boto_client.return_value = s3_client
    lineage_run_id = "44444444-4444-4444-8444-444444444444"
    event = build_athena_lineage_event(RunState.START, lineage_run_id)

    transport = S3Transport(S3_LINEAGE_EVENT_PATH)
    transport.emit(event)

    mock_boto_client.assert_called_once_with("s3")
    s3_client.put_object.assert_called_once()

    call = s3_client.put_object.call_args.kwargs

    assert call["Bucket"] == "imungai-healthcare-realtime"
    assert call["Key"].startswith("lineage/openlineage/athena/event-")
    assert call["Key"].endswith(".json")
    assert call["ContentType"] == "application/json"
    assert lineage_run_id.encode() in call["Body"]


def test_s3_transport_rejects_invalid_path() -> None:
    with pytest.raises(ValueError, match="Invalid S3 lineage event path"):
        S3Transport("lineage/openlineage/athena/event")


def test_athena_start_complete_lifecycle_uses_same_run_id() -> None:
    lineage_run_id = "11111111-1111-4111-8111-111111111111"

    start_event = build_athena_lineage_event(RunState.START, lineage_run_id)
    complete_event = build_athena_lineage_event(RunState.COMPLETE, lineage_run_id)

    assert start_event.eventType == RunState.START
    assert complete_event.eventType == RunState.COMPLETE
    assert start_event.run.runId == lineage_run_id
    assert complete_event.run.runId == lineage_run_id
    assert start_event.run.runId == complete_event.run.runId


def test_athena_start_fail_lifecycle_uses_same_run_id() -> None:
    lineage_run_id = "22222222-2222-4222-8222-222222222222"

    start_event = build_athena_lineage_event(RunState.START, lineage_run_id)
    fail_event = build_athena_lineage_event(RunState.FAIL, lineage_run_id)

    assert start_event.eventType == RunState.START
    assert fail_event.eventType == RunState.FAIL
    assert start_event.run.runId == lineage_run_id
    assert fail_event.run.runId == lineage_run_id
    assert start_event.run.runId == fail_event.run.runId


def test_athena_lifecycle_preserves_datasets() -> None:
    lineage_run_id = "33333333-3333-4333-8333-333333333333"

    event = build_athena_lineage_event(RunState.COMPLETE, lineage_run_id)

    assert event.inputs == [PROCESSED_DATASET]
    assert event.outputs == [VALIDATION_DATASET]


@patch("airflow.dags.lib.athena_lineage.emit_athena_lineage_event")
@patch("airflow.dags.lib.athena_lineage.boto3.client")
def test_run_athena_validation_emits_start_complete(mock_boto_client: MagicMock, mock_emit: MagicMock) -> None:
    from airflow.dags.lib.athena_lineage import run_athena_validation

    athena_client = MagicMock()
    athena_client.start_query_execution.return_value = {"QueryExecutionId": "query-123"}
    athena_client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    mock_boto_client.return_value = athena_client

    result = run_athena_validation()

    assert result == "query-123"
    assert mock_emit.call_count == 2
    assert mock_emit.call_args_list[0].args[0] == RunState.START
    assert mock_emit.call_args_list[1].args[0] == RunState.COMPLETE
    assert mock_emit.call_args_list[0].args[1] == mock_emit.call_args_list[1].args[1]


@patch("airflow.dags.lib.athena_lineage.emit_athena_lineage_event")
@patch("airflow.dags.lib.athena_lineage.boto3.client")
def test_run_athena_validation_emits_start_fail(mock_boto_client: MagicMock, mock_emit: MagicMock) -> None:
    from airflow.dags.lib.athena_lineage import run_athena_validation

    athena_client = MagicMock()
    athena_client.start_query_execution.return_value = {"QueryExecutionId": "query-456"}
    athena_client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": "validation error"}}}
    mock_boto_client.return_value = athena_client

    with pytest.raises(RuntimeError, match="validation error"):
        run_athena_validation()

    assert mock_emit.call_count == 2
    assert mock_emit.call_args_list[0].args[0] == RunState.START
    assert mock_emit.call_args_list[1].args[0] == RunState.FAIL
    assert mock_emit.call_args_list[0].args[1] == mock_emit.call_args_list[1].args[1]