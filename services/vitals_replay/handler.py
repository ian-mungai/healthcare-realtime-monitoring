import json
import os
from typing import Any

import boto3

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
KINESIS_STREAM_ARN = os.environ["KINESIS_STREAM_ARN"]
MAX_REPLAY_ATTEMPTS = int(os.getenv("MAX_REPLAY_ATTEMPTS", "1"))
MAX_GET_RECORDS_CALLS = 10
GET_RECORDS_LIMIT = 100

kinesis = boto3.client("kinesis", region_name=AWS_REGION)


def parse_failure_message(record: dict[str, Any]) -> dict[str, str]:
    body = json.loads(record["body"])
    batch_info = body.get("KinesisBatchInfo")

    if not batch_info:
        raise ValueError("KinesisBatchInfo is required")

    required_fields = ["shardId", "startSequenceNumber", "endSequenceNumber", "streamArn"]
    missing_fields = [field for field in required_fields if not batch_info.get(field)]

    if missing_fields:
        raise ValueError(f"Missing KinesisBatchInfo field(s): {', '.join(missing_fields)}")

    if batch_info["streamArn"] != KINESIS_STREAM_ARN:
        raise ValueError(f"Unexpected Kinesis stream ARN: {batch_info['streamArn']}")

    return {
        "shard_id": batch_info["shardId"],
        "start_sequence_number": batch_info["startSequenceNumber"],
        "end_sequence_number": batch_info["endSequenceNumber"],
    }


def get_failed_records(shard_id: str, start_sequence_number: str, end_sequence_number: str) -> list[dict[str, Any]]:
    iterator_response = kinesis.get_shard_iterator(
        StreamARN=KINESIS_STREAM_ARN, ShardId=shard_id, ShardIteratorType="AT_SEQUENCE_NUMBER", StartingSequenceNumber=start_sequence_number
    )

    shard_iterator = iterator_response["ShardIterator"]
    failed_records: list[dict[str, Any]] = []
    end_sequence = int(end_sequence_number)
    reached_end = False

    for _ in range(MAX_GET_RECORDS_CALLS):
        response = kinesis.get_records(ShardIterator=shard_iterator, Limit=GET_RECORDS_LIMIT)
        shard_iterator = response.get("NextShardIterator")

        for record in response.get("Records", []):
            sequence_number = int(record["SequenceNumber"])

            if sequence_number > end_sequence:
                reached_end = True
                break

            failed_records.append(record)

            if sequence_number == end_sequence:
                reached_end = True
                break

        if reached_end or not shard_iterator:
            break

    if not failed_records:
        raise RuntimeError("No source Kinesis records were found for the failed sequence range")

    if not reached_end:
        raise RuntimeError(f"Unable to retrieve complete failed Kinesis sequence range ending at {end_sequence_number}")

    return failed_records


def build_replay_entry(record: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(record["Data"].decode("utf-8"))
    replay_attempt = int(payload.get("_replay_attempt", 0))

    if replay_attempt >= MAX_REPLAY_ATTEMPTS:
        raise RuntimeError(f"Automatic replay limit reached at attempt {replay_attempt}")

    payload["_replay_attempt"] = replay_attempt + 1

    entry: dict[str, Any] = {"Data": json.dumps(payload, separators=(",", ":")).encode("utf-8"), "PartitionKey": record["PartitionKey"]}

    if record.get("ExplicitHashKey"):
        entry["ExplicitHashKey"] = record["ExplicitHashKey"]

    return entry


def build_replay_entries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_replay_entry(record) for record in records]


def replay_records(records: list[dict[str, Any]]) -> int:
    entries = build_replay_entries(records)

    response = kinesis.put_records(StreamARN=KINESIS_STREAM_ARN, Records=entries)

    failed_record_count = response.get("FailedRecordCount", 0)

    if failed_record_count:
        raise RuntimeError(f"Kinesis replay failed for {failed_record_count} record(s)")

    return len(entries)


def process_sqs_record(record: dict[str, Any]) -> int:
    failure = parse_failure_message(record)
    records = get_failed_records(failure["shard_id"], failure["start_sequence_number"], failure["end_sequence_number"])

    return replay_records(records)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    batch_item_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_id = record["messageId"]

        try:
            replayed_count = process_sqs_record(record)

            print(f"Replayed {replayed_count} Kinesis record(s) for SQS message {message_id}")

        except Exception as error:
            print(f"Failed replay for SQS message {message_id}: {error}")

            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
