import importlib
import json
import os
from unittest.mock import patch

import pytest

os.environ["KINESIS_STREAM_ARN"] = "arn:aws:kinesis:example-region-1:123456789012:stream/healthcare_realtime_vitals"

from services.vitals_replay import handler

handler = importlib.reload(handler)


def build_sqs_record(message_id: str = "message-1", stream_arn: str | None = None) -> dict:
    body = {
        "KinesisBatchInfo": {
            "shardId": "shardId-000000000000",
            "startSequenceNumber": "100",
            "endSequenceNumber": "101",
            "streamArn": stream_arn or handler.KINESIS_STREAM_ARN,
        }
    }

    return {"messageId": message_id, "body": json.dumps(body)}


def test_parse_failure_message() -> None:
    failure = handler.parse_failure_message(build_sqs_record())

    assert failure == {"shard_id": "shardId-000000000000", "start_sequence_number": "100", "end_sequence_number": "101"}


def test_parse_failure_message_requires_batch_info() -> None:
    record = {"messageId": "message-1", "body": json.dumps({})}

    with pytest.raises(ValueError, match="KinesisBatchInfo is required"):
        handler.parse_failure_message(record)


def test_parse_failure_message_rejects_unexpected_stream() -> None:
    record = build_sqs_record(stream_arn="arn:aws:kinesis:example-region-1:123456789012:stream/unexpected")

    with pytest.raises(ValueError, match="Unexpected Kinesis stream ARN"):
        handler.parse_failure_message(record)


@patch("services.vitals_replay.handler.kinesis")
def test_get_failed_records_reads_sequence_range(kinesis) -> None:
    kinesis.get_shard_iterator.return_value = {"ShardIterator": "iterator-1"}
    kinesis.get_records.return_value = {
        "Records": [
            {"SequenceNumber": "100", "Data": b"record-100", "PartitionKey": "patient-1"},
            {"SequenceNumber": "101", "Data": b"record-101", "PartitionKey": "patient-1"},
            {"SequenceNumber": "102", "Data": b"record-102", "PartitionKey": "patient-1"},
        ],
        "NextShardIterator": "iterator-2",
    }

    records = handler.get_failed_records("shardId-000000000000", "100", "101")

    assert [record["SequenceNumber"] for record in records] == ["100", "101"]

    kinesis.get_shard_iterator.assert_called_once_with(
        StreamARN=handler.KINESIS_STREAM_ARN, ShardId="shardId-000000000000", ShardIteratorType="AT_SEQUENCE_NUMBER", StartingSequenceNumber="100"
    )


@patch("services.vitals_replay.handler.kinesis")
def test_get_failed_records_follows_next_iterator(kinesis) -> None:
    kinesis.get_shard_iterator.return_value = {"ShardIterator": "iterator-1"}
    kinesis.get_records.side_effect = [
        {"Records": [], "NextShardIterator": "iterator-2"},
        {
            "Records": [
                {"SequenceNumber": "100", "Data": b"record-100", "PartitionKey": "patient-1"},
                {"SequenceNumber": "101", "Data": b"record-101", "PartitionKey": "patient-1"},
            ],
            "NextShardIterator": "iterator-3",
        },
    ]

    records = handler.get_failed_records("shardId-000000000000", "100", "101")

    assert len(records) == 2
    assert kinesis.get_records.call_count == 2


@patch("services.vitals_replay.handler.kinesis")
def test_get_failed_records_raises_when_no_source_records_exist(kinesis) -> None:
    kinesis.get_shard_iterator.return_value = {"ShardIterator": "iterator-1"}
    kinesis.get_records.return_value = {"Records": [], "NextShardIterator": None}

    with pytest.raises(RuntimeError, match="No source Kinesis records were found"):
        handler.get_failed_records("shardId-000000000000", "100", "101")


def test_build_replay_entries_adds_replay_attempt_and_preserves_partition_key() -> None:
    records = [{"SequenceNumber": "100", "Data": b'{"patient_id":"137506799"}', "PartitionKey": "137506799"}]

    entries = handler.build_replay_entries(records)

    assert json.loads(entries[0]["Data"]) == {"patient_id": "137506799", "_replay_attempt": 1}
    assert entries[0]["PartitionKey"] == "137506799"


def test_build_replay_entries_rejects_record_at_replay_limit() -> None:
    records = [{"SequenceNumber": "100", "Data": b'{"patient_id":"137506799","_replay_attempt":1}', "PartitionKey": "137506799"}]

    with pytest.raises(RuntimeError, match="Automatic replay limit reached"):
        handler.build_replay_entries(records)


@patch("services.vitals_replay.handler.kinesis")
def test_replay_records_puts_records_back_to_stream(kinesis) -> None:
    kinesis.put_records.return_value = {"FailedRecordCount": 0, "Records": [{"SequenceNumber": "200", "ShardId": "shardId-000000000000"}]}

    records = [{"SequenceNumber": "100", "Data": b'{"patient_id":"137506799"}', "PartitionKey": "137506799"}]

    replayed_count = handler.replay_records(records)

    assert replayed_count == 1

    kinesis.put_records.assert_called_once_with(
        StreamARN=handler.KINESIS_STREAM_ARN, Records=[{"Data": b'{"patient_id":"137506799","_replay_attempt":1}', "PartitionKey": "137506799"}]
    )


@patch("services.vitals_replay.handler.kinesis")
def test_replay_records_raises_on_partial_put_failure(kinesis) -> None:
    kinesis.put_records.return_value = {"FailedRecordCount": 1, "Records": [{"ErrorCode": "ProvisionedThroughputExceededException"}]}

    records = [{"SequenceNumber": "100", "Data": b'{"patient_id":"patient-1"}', "PartitionKey": "patient-1"}]

    with pytest.raises(RuntimeError, match=r"Kinesis replay failed for 1 record\(s\)"):
        handler.replay_records(records)


@patch("services.vitals_replay.handler.process_sqs_record")
def test_lambda_handler_processes_message(process_sqs_record) -> None:
    process_sqs_record.return_value = 2

    result = handler.lambda_handler({"Records": [build_sqs_record()]}, None)

    process_sqs_record.assert_called_once()
    assert result == {"batchItemFailures": []}


@patch("services.vitals_replay.handler.process_sqs_record")
def test_lambda_handler_reports_failed_sqs_message(process_sqs_record) -> None:
    process_sqs_record.side_effect = RuntimeError("Replay failure")

    result = handler.lambda_handler({"Records": [build_sqs_record(message_id="failed-message")]}, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "failed-message"}]}


@patch("services.vitals_replay.handler.process_sqs_record")
def test_lambda_handler_supports_partial_sqs_batch_failure(process_sqs_record) -> None:
    process_sqs_record.side_effect = [1, RuntimeError("Replay failure")]

    event = {"Records": [build_sqs_record(message_id="successful-message"), build_sqs_record(message_id="failed-message")]}

    result = handler.lambda_handler(event, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "failed-message"}]}
