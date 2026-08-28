import base64
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from services.vitals_stream_processor.handler import decode_kinesis_record, lambda_handler, to_dynamodb_item


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


@patch("services.vitals_stream_processor.handler.get_connection_ids")
@patch("services.vitals_stream_processor.handler.boto3.client")
def test_push_vitals_sends_to_connections(boto_client, get_connection_ids, monkeypatch) -> None:
    from services.vitals_stream_processor import handler

    monkeypatch.setattr(handler, "WEBSOCKET_ENDPOINT", "https://example.execute-api.us-east-1.amazonaws.com/development")

    get_connection_ids.return_value = ["connection-1", "connection-2"]

    api_gateway = MagicMock()
    boto_client.return_value = api_gateway

    deliveries, failures, active_connections = handler.push_vitals({"patient_id": "137506799", "heart_rate": 96.0})

    assert api_gateway.post_to_connection.call_count == 2
    assert deliveries == 2
    assert failures == 0
    assert active_connections == 2


def test_calculate_latency_ms() -> None:
    from datetime import UTC, datetime, timedelta
    from unittest.mock import patch

    from services.vitals_stream_processor import handler

    current_time = datetime(2026, 8, 28, 16, 0, 5, tzinfo=UTC)
    event_time = current_time - timedelta(seconds=2)

    with patch("services.vitals_stream_processor.handler.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = current_time
        mocked_datetime.fromisoformat.return_value = event_time

        latency = handler.calculate_latency_ms("2026-08-28T16:00:03Z")

    assert latency == 2000.0
