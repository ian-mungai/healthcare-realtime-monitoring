import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from services.vitals_stream_processor.handler import (
    calculate_latency_ms,
    decode_kinesis_record,
    get_patient_connections,
    lambda_handler,
    push_vitals,
    to_dynamodb_item,
)


def build_kinesis_record(payload: dict, sequence_number: str = "1") -> dict:
    encoded_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

    return {"kinesis": {"data": encoded_payload, "sequenceNumber": sequence_number}}


def test_decode_kinesis_record() -> None:
    payload = {
        "patient_id": "137506799",
        "source_record_id": "bidmc01n",
        "event_timestamp": "2026-08-27T16:00:00Z",
        "heart_rate": 94.0,
        "respiratory_rate": 25.0,
        "spo2": 97.0,
        "systolic_bp": 118.0,
        "diastolic_bp": 76.0,
    }

    assert decode_kinesis_record(build_kinesis_record(payload)) == payload


def test_to_dynamodb_item_converts_floats() -> None:
    payload = {"patient_id": "137506799", "heart_rate": 94.5}

    item = to_dynamodb_item(payload)

    assert item["patient_id"] == "137506799"
    assert item["heart_rate"] == Decimal("94.5")


@patch("services.vitals_stream_processor.handler.emit_metrics")
@patch("services.vitals_stream_processor.handler.push_vitals")
@patch("services.vitals_stream_processor.handler.write_latest_vitals")
def test_lambda_handler_processes_record(write_latest_vitals, push_vitals, emit_metrics) -> None:
    payload = {"patient_id": "137506799", "heart_rate": 94.0}

    push_vitals.return_value = (1, 0, 1)

    result = lambda_handler({"Records": [build_kinesis_record(payload)]}, None)

    write_latest_vitals.assert_called_once_with(payload)
    push_vitals.assert_called_once_with(payload)
    emit_metrics.assert_called_once()

    assert result == {"batchItemFailures": []}


@patch("services.vitals_stream_processor.handler.write_latest_vitals")
def test_lambda_handler_reports_failed_record(write_latest_vitals) -> None:
    write_latest_vitals.side_effect = RuntimeError("DynamoDB failure")

    event = {"Records": [build_kinesis_record({"patient_id": "137506799", "heart_rate": 94.0}, sequence_number="12345")]}

    result = lambda_handler(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "12345"}]}


@patch("services.vitals_stream_processor.handler.connections_table")
def test_get_patient_connections_queries_patient_index(connections_table) -> None:
    connections_table.query.return_value = {"Items": [{"connection_id": "connection-1"}, {"connection_id": "connection-2"}]}

    connection_ids = get_patient_connections("137506799")

    assert connection_ids == ["connection-1", "connection-2"]

    connections_table.query.assert_called_once()

    query_arguments = connections_table.query.call_args.kwargs

    assert query_arguments["IndexName"] == "patient_id-index"
    assert query_arguments["ProjectionExpression"] == "connection_id"


@patch("services.vitals_stream_processor.handler.connections_table")
def test_get_patient_connections_handles_pagination(connections_table) -> None:
    connections_table.query.side_effect = [
        {"Items": [{"connection_id": "connection-1"}], "LastEvaluatedKey": {"patient_id": "137506799", "connection_id": "connection-1"}},
        {"Items": [{"connection_id": "connection-2"}]},
    ]

    connection_ids = get_patient_connections("137506799")

    assert connection_ids == ["connection-1", "connection-2"]

    assert connections_table.query.call_count == 2

    second_query_arguments = connections_table.query.call_args_list[1].kwargs

    assert second_query_arguments["ExclusiveStartKey"] == {"patient_id": "137506799", "connection_id": "connection-1"}


@patch("services.vitals_stream_processor.handler.connections_table")
def test_get_patient_connections_returns_empty_list(connections_table) -> None:
    connections_table.query.return_value = {"Items": []}

    connection_ids = get_patient_connections("137506799")

    assert connection_ids == []

    connections_table.query.assert_called_once()


@patch("services.vitals_stream_processor.handler.get_patient_connections")
@patch("services.vitals_stream_processor.handler.boto3.client")
def test_push_vitals_sends_to_patient_connections(boto_client, get_patient_connections_mock, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.us-east-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = ["connection-1", "connection-2"]

    api_gateway = MagicMock()
    boto_client.return_value = api_gateway

    payload = {"patient_id": "137506799", "heart_rate": 96.0}

    deliveries, failures, active_connections = push_vitals(payload)

    get_patient_connections_mock.assert_called_once_with("137506799")

    assert api_gateway.post_to_connection.call_count == 2
    assert deliveries == 2
    assert failures == 0
    assert active_connections == 2


@patch("services.vitals_stream_processor.handler.get_patient_connections")
@patch("services.vitals_stream_processor.handler.boto3.client")
def test_push_vitals_uses_payload_patient_id(boto_client, get_patient_connections_mock, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.us-east-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = []
    boto_client.return_value = MagicMock()

    payload = {"patient_id": "999999999", "heart_rate": 150.0}

    deliveries, failures, active_connections = push_vitals(payload)

    get_patient_connections_mock.assert_called_once_with("999999999")

    assert deliveries == 0
    assert failures == 0
    assert active_connections == 0


@patch("services.vitals_stream_processor.handler.delete_connection")
@patch("services.vitals_stream_processor.handler.get_patient_connections")
@patch("services.vitals_stream_processor.handler.boto3.client")
def test_push_vitals_deletes_stale_connection(boto_client, get_patient_connections_mock, delete_connection, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.us-east-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = ["stale-connection"]

    api_gateway = MagicMock()

    api_gateway.post_to_connection.side_effect = ClientError(
        {"Error": {"Code": "GoneException", "Message": "Gone"}, "ResponseMetadata": {"HTTPStatusCode": 410}}, "PostToConnection"
    )

    boto_client.return_value = api_gateway

    payload = {"patient_id": "137506799", "heart_rate": 96.0}

    deliveries, failures, active_connections = push_vitals(payload)

    delete_connection.assert_called_once_with("stale-connection")

    assert deliveries == 0
    assert failures == 0
    assert active_connections == 1


@patch("services.vitals_stream_processor.handler.delete_connection")
@patch("services.vitals_stream_processor.handler.get_patient_connections")
@patch("services.vitals_stream_processor.handler.boto3.client")
def test_push_vitals_counts_non_410_delivery_failure(boto_client, get_patient_connections_mock, delete_connection, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.us-east-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = ["connection-1"]

    api_gateway = MagicMock()

    api_gateway.post_to_connection.side_effect = ClientError(
        {"Error": {"Code": "InternalServerErrorException", "Message": "Internal error"}, "ResponseMetadata": {"HTTPStatusCode": 500}}, "PostToConnection"
    )

    boto_client.return_value = api_gateway

    payload = {"patient_id": "137506799", "heart_rate": 96.0}

    deliveries, failures, active_connections = push_vitals(payload)

    delete_connection.assert_not_called()

    assert deliveries == 0
    assert failures == 1
    assert active_connections == 1


@patch("services.vitals_stream_processor.handler.boto3.client")
def test_push_vitals_requires_patient_id(boto_client, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.us-east-1.amazonaws.com/development")

    payload = {"heart_rate": 96.0}

    with pytest.raises(ValueError, match="patient_id is required"):
        push_vitals(payload)

    boto_client.assert_not_called()


def test_calculate_latency_ms() -> None:
    current_time = datetime(2026, 8, 28, 16, 0, 5, tzinfo=UTC)

    event_time = current_time - timedelta(seconds=2)

    with patch("services.vitals_stream_processor.handler.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = current_time
        mocked_datetime.fromisoformat.return_value = event_time

        latency = calculate_latency_ms("2026-08-28T16:00:03Z")

    assert latency == 2000.0
