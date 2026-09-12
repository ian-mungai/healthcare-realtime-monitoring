import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from services.vitals_stream_processor.handler import (
    calculate_latency_ms,
    claim_observation,
    complete_observation_claim,
    decode_kinesis_record,
    get_patient_connections,
    lambda_handler,
    push_vitals,
    to_dynamodb_item,
    write_latest_vitals,
    write_load_test_result,
)
from services.vitals_stream_processor.schema import PermanentRecordError


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


@pytest.mark.parametrize("encoded_data", ["not-base64!", base64.b64encode(b"not-json").decode("utf-8"), base64.b64encode(b"[]").decode("utf-8")])
def test_decode_kinesis_record_rejects_malformed_payload(encoded_data: str) -> None:
    with pytest.raises(PermanentRecordError):
        decode_kinesis_record({"kinesis": {"data": encoded_data}})


def test_to_dynamodb_item_converts_floats() -> None:
    payload = {"patient_id": "137506799", "heart_rate": 94.5}

    item = to_dynamodb_item(payload)

    assert item["patient_id"] == "137506799"
    assert item["heart_rate"] == Decimal("94.5")


@patch("services.vitals_stream_processor.handler.latest_vitals_table")
def test_write_latest_vitals_merges_partial_updates_with_equal_timestamps(latest_vitals_table) -> None:
    payload = {"patient_id": "1000", "encounter_id": "encounter_456", "event_timestamp": "2026-08-31T22:42:19Z", "spo2": 97.0, "_replay_attempt": 1}

    assert write_latest_vitals(payload) is True

    arguments = latest_vitals_table.update_item.call_args.kwargs
    assert arguments["Key"] == {"patient_id": "1000"}
    assert arguments["ConditionExpression"] == "(attribute_not_exists(#event_epoch_0) OR #event_epoch_0 <= :incoming_event_epoch)"
    assert "patient_id" not in arguments["ExpressionAttributeNames"].values()
    assert "spo2" in arguments["ExpressionAttributeNames"].values()
    assert "encounter_id" in arguments["ExpressionAttributeNames"].values()
    assert "encounter_456" in arguments["ExpressionAttributeValues"].values()
    assert "spo2_event_timestamp" in arguments["ExpressionAttributeNames"].values()
    assert "REMOVE" in arguments["UpdateExpression"]
    assert "_replay_attempt" in arguments["ExpressionAttributeNames"].values()
    assert Decimal("1") not in arguments["ExpressionAttributeValues"].values()
    assert Decimal("97.0") in arguments["ExpressionAttributeValues"].values()


@patch("services.vitals_stream_processor.handler.idempotency_table")
def test_claim_observation_rejects_duplicate_observation_id(idempotency_table) -> None:
    error_response = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "duplicate"}, "ResponseMetadata": {"HTTPStatusCode": 400}}
    idempotency_table.put_item.side_effect = ClientError(cast(Any, error_response), "PutItem")

    assert claim_observation({"observation_id": "observation-1"}) is None


@patch("services.vitals_stream_processor.handler.uuid4", return_value="claim-token")
@patch("services.vitals_stream_processor.handler.idempotency_table")
def test_claim_observation_uses_expiring_owner_lease(idempotency_table, _uuid4) -> None:
    current_time = datetime(2026, 9, 11, 12, tzinfo=UTC)

    with patch("services.vitals_stream_processor.handler.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = current_time
        assert claim_observation({"observation_id": "observation-1"}) == "claim-token"

    arguments = idempotency_table.put_item.call_args.kwargs
    assert arguments["Item"]["status"] == "processing"
    assert arguments["Item"]["claim_token"] == "claim-token"
    assert arguments["Item"]["lease_expires_at"] == int(current_time.timestamp()) + 60
    assert "#lease_expires_at < :now_epoch" in arguments["ConditionExpression"]


@patch("services.vitals_stream_processor.handler.idempotency_table")
def test_complete_observation_claim_requires_owner_token(idempotency_table) -> None:
    complete_observation_claim("observation-1", "claim-token")

    arguments = idempotency_table.update_item.call_args.kwargs
    assert arguments["Key"] == {"observation_id": "observation-1"}
    assert arguments["ConditionExpression"] == "#claim_token = :claim_token"
    assert arguments["ExpressionAttributeValues"][":claim_token"] == "claim-token"
    assert "REMOVE #claim_token, #lease_expires_at" in arguments["UpdateExpression"]


@patch("services.vitals_stream_processor.handler.latest_vitals_table")
def test_write_latest_vitals_ignores_stale_updates(latest_vitals_table) -> None:
    error_response = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "stale"}, "ResponseMetadata": {"HTTPStatusCode": 400}}
    latest_vitals_table.update_item.side_effect = ClientError(cast(Any, error_response), "UpdateItem")

    assert write_latest_vitals({"patient_id": "1000", "event_timestamp": "2026-08-31T22:42:19Z", "heart_rate": 82.0}) is False


@patch("services.vitals_stream_processor.handler.load_test_results_table")
def test_write_load_test_result_records_processing_time_and_expiry(load_test_results_table) -> None:
    payload = {
        "schema_version": "1.0",
        "observation_id": "load-test-run-01-00000001",
        "patient_id": "load_test_patient_01",
        "source": "load_test",
        "event_timestamp": "2026-09-09T12:00:00Z",
        "heart_rate": 82.0,
    }
    current_time = datetime(2026, 9, 9, 12, 0, 1, tzinfo=UTC)

    with patch("services.vitals_stream_processor.handler.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = current_time
        write_load_test_result(payload)

    item = load_test_results_table.put_item.call_args.kwargs["Item"]
    assert item["observation_id"] == payload["observation_id"]
    assert item["processed_at"] == "2026-09-09T12:00:01Z"
    assert item["expires_at"] == int(current_time.timestamp()) + 86400


@patch("services.vitals_stream_processor.handler.emit_metrics")
@patch("services.vitals_stream_processor.handler.complete_observation_claim")
@patch("services.vitals_stream_processor.handler.push_vitals")
@patch("services.vitals_stream_processor.handler.write_latest_vitals")
@patch("services.vitals_stream_processor.handler.claim_observation", return_value="claim-token")
def test_lambda_handler_processes_record(claim_observation, write_latest_vitals, push_vitals, complete_observation_claim, emit_metrics) -> None:
    payload = {
        "schema_version": "1.0",
        "observation_id": "observation_123",
        "patient_id": "137506799",
        "source": "bidmc",
        "event_timestamp": "2026-08-31T22:42:19Z",
        "heart_rate": 94.0,
    }
    push_vitals.return_value = (1, 0, 1)

    result = lambda_handler({"Records": [build_kinesis_record(payload)]}, None)

    write_latest_vitals.assert_called_once_with(payload)
    push_vitals.assert_called_once_with(payload)
    complete_observation_claim.assert_called_once_with("observation_123", "claim-token")
    emit_metrics.assert_called_once()

    assert result == {"batchItemFailures": []}


@patch("services.vitals_stream_processor.handler.emit_metrics")
@patch("services.vitals_stream_processor.handler.complete_observation_claim")
@patch("services.vitals_stream_processor.handler.push_vitals")
@patch("services.vitals_stream_processor.handler.write_latest_vitals")
@patch("services.vitals_stream_processor.handler.write_load_test_result")
@patch("services.vitals_stream_processor.handler.claim_observation", return_value="claim-token")
def test_lambda_handler_isolates_load_test_record(
    claim_observation, write_load_test_result, write_latest_vitals, push_vitals, complete_observation_claim, emit_metrics
) -> None:
    payload = {
        "schema_version": "1.0",
        "observation_id": "load-test-run-01-00000001",
        "patient_id": "load_test_patient_01",
        "source": "load_test",
        "event_timestamp": "2026-09-09T12:00:00Z",
        "heart_rate": 82.0,
    }
    push_vitals.return_value = (1, 0, 1)

    result = lambda_handler({"Records": [build_kinesis_record(payload)]}, None)

    write_load_test_result.assert_called_once_with(payload)
    write_latest_vitals.assert_not_called()
    push_vitals.assert_called_once_with(payload)
    complete_observation_claim.assert_called_once_with("load-test-run-01-00000001", "claim-token")
    metric_data = emit_metrics.call_args.args[0]
    assert {metric["MetricName"] for metric in metric_data} == {
        "RecordsProcessed",
        "WebSocketDeliveries",
        "WebSocketDeliveryFailures",
        "ActiveConnections",
        "ProcessingLatencyMilliseconds",
    }
    assert emit_metrics.call_args.kwargs == {"namespace": "HealthcareRealtime/LoadTest"}
    assert result == {"batchItemFailures": []}


@patch("services.vitals_stream_processor.handler.release_observation_claim")
@patch("services.vitals_stream_processor.handler.claim_observation", return_value="claim-token")
@patch("services.vitals_stream_processor.handler.write_latest_vitals")
@pytest.mark.parametrize("error", [RuntimeError("DynamoDB failure"), KeyError("response field"), TypeError("implementation failure")])
def test_lambda_handler_reports_failed_record(write_latest_vitals, claim_observation, release_observation_claim, error: Exception) -> None:
    write_latest_vitals.side_effect = error

    payload = {
        "schema_version": "1.0",
        "observation_id": "observation-1",
        "patient_id": "137506799",
        "source": "bidmc",
        "event_timestamp": "2026-08-31T22:42:19Z",
        "heart_rate": 94.0,
    }
    event = {"Records": [build_kinesis_record(payload, sequence_number="12345")]}

    result = lambda_handler(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "12345"}]}
    release_observation_claim.assert_called_once_with("observation-1", "claim-token")


@patch("services.vitals_stream_processor.handler.emit_metrics")
def test_lambda_handler_drops_permanently_invalid_record(emit_metrics) -> None:
    event = {"Records": [build_kinesis_record({"patient_id": "137506799", "heart_rate": 94.0}, sequence_number="12345")]}

    result = lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    metric_data = emit_metrics.call_args.args[0]
    assert metric_data == [{"MetricName": "PermanentRecordsRejected", "Value": 1, "Unit": "Count"}]


@patch("services.vitals_stream_processor.handler.emit_metrics")
@patch("services.vitals_stream_processor.handler.claim_observation", return_value=None)
def test_lambda_handler_batches_duplicate_metrics_once(claim_observation, emit_metrics) -> None:
    payload = {
        "schema_version": "1.0",
        "observation_id": "observation-1",
        "patient_id": "137506799",
        "source": "bidmc",
        "event_timestamp": "2026-08-31T22:42:19Z",
        "heart_rate": 94.0,
    }

    result = lambda_handler({"Records": [build_kinesis_record(payload, "1"), build_kinesis_record(payload, "2")]}, None)

    assert result == {"batchItemFailures": []}
    emit_metrics.assert_called_once()
    metric_names = [metric["MetricName"] for metric in emit_metrics.call_args.args[0]]
    assert metric_names.count("DuplicatesSkipped") == 2


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
@patch("services.vitals_stream_processor.handler.get_api_gateway_client")
def test_push_vitals_sends_to_patient_connections(get_api_gateway_client, get_patient_connections_mock, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.example-region-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = ["connection-1", "connection-2"]

    api_gateway = MagicMock()
    get_api_gateway_client.return_value = api_gateway

    payload = {"patient_id": "137506799", "heart_rate": 96.0}

    deliveries, failures, active_connections = push_vitals(payload)

    get_patient_connections_mock.assert_called_once_with("137506799")

    assert api_gateway.post_to_connection.call_count == 2
    assert deliveries == 2
    assert failures == 0
    assert active_connections == 2


@patch("services.vitals_stream_processor.handler.get_patient_connections")
@patch("services.vitals_stream_processor.handler.get_api_gateway_client")
def test_push_vitals_uses_payload_patient_id(get_api_gateway_client, get_patient_connections_mock, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.example-region-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = []
    get_api_gateway_client.return_value = MagicMock()

    payload = {"patient_id": "999999999", "heart_rate": 150.0}

    deliveries, failures, active_connections = push_vitals(payload)

    get_patient_connections_mock.assert_called_once_with("999999999")

    assert deliveries == 0
    assert failures == 0
    assert active_connections == 0


@patch("services.vitals_stream_processor.handler.delete_connection")
@patch("services.vitals_stream_processor.handler.get_patient_connections")
@patch("services.vitals_stream_processor.handler.get_api_gateway_client")
def test_push_vitals_deletes_stale_connection(get_api_gateway_client, get_patient_connections_mock, delete_connection, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.example-region-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = ["stale-connection"]

    api_gateway = MagicMock()

    gone_error = {"Error": {"Code": "GoneException", "Message": "Gone"}, "ResponseMetadata": {"HTTPStatusCode": 410}}
    api_gateway.post_to_connection.side_effect = ClientError(cast(Any, gone_error), "PostToConnection")

    get_api_gateway_client.return_value = api_gateway

    payload = {"patient_id": "137506799", "heart_rate": 96.0}

    deliveries, failures, active_connections = push_vitals(payload)

    delete_connection.assert_called_once_with("stale-connection")

    assert deliveries == 0
    assert failures == 0
    assert active_connections == 1


@patch("services.vitals_stream_processor.handler.delete_connection")
@patch("services.vitals_stream_processor.handler.get_patient_connections")
@patch("services.vitals_stream_processor.handler.get_api_gateway_client")
def test_push_vitals_counts_non_410_delivery_failure(get_api_gateway_client, get_patient_connections_mock, delete_connection, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.example-region-1.amazonaws.com/development")

    get_patient_connections_mock.return_value = ["connection-1"]

    api_gateway = MagicMock()

    internal_error = {"Error": {"Code": "InternalServerErrorException", "Message": "Internal error"}, "ResponseMetadata": {"HTTPStatusCode": 500}}
    api_gateway.post_to_connection.side_effect = ClientError(cast(Any, internal_error), "PostToConnection")

    get_api_gateway_client.return_value = api_gateway

    payload = {"patient_id": "137506799", "heart_rate": 96.0}

    deliveries, failures, active_connections = push_vitals(payload)

    delete_connection.assert_not_called()

    assert deliveries == 0
    assert failures == 1
    assert active_connections == 1


@patch("services.vitals_stream_processor.handler.get_api_gateway_client")
def test_push_vitals_requires_patient_id(get_api_gateway_client, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.example-region-1.amazonaws.com/development")

    payload = {"heart_rate": 96.0}

    with pytest.raises(ValueError, match="patient_id is required"):
        push_vitals(payload)

    get_api_gateway_client.assert_not_called()


def test_calculate_latency_ms() -> None:
    current_time = datetime(2026, 8, 28, 16, 0, 5, tzinfo=UTC)

    event_time = current_time - timedelta(seconds=2)

    with patch("services.vitals_stream_processor.handler.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = current_time
        mocked_datetime.fromisoformat.return_value = event_time

        latency = calculate_latency_ms("2026-08-28T16:00:03Z")

    assert latency == 2000.0
