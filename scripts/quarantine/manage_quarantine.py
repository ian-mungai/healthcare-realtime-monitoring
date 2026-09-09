import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import boto3

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
DEFAULT_PREFIX = "quarantine/fhir_observations/"

LOINC_TO_VITAL = {"8867-4": "heart_rate", "9279-1": "respiratory_rate", "2708-6": "spo2", "8480-6": "systolic_bp", "8462-4": "diastolic_bp"}


def iter_quarantine_records(s3_client: Any, bucket: str, prefix: str) -> Iterable[dict[str, Any]]:
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if not key or key.endswith("/"):
                continue

            body = s3_client.get_object(Bucket=bucket, Key=key)["Body"]
            for line_number, raw_line in enumerate(body.iter_lines(), start=1):
                if not raw_line:
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid quarantine JSON in s3://{bucket}/{key} at line {line_number}") from error
                if isinstance(record, dict):
                    yield record


def export_records(records: Iterable[dict[str, Any]], output_path: Path, rejection_reason: str | None = None) -> int:
    selected = [record for record in records if rejection_reason is None or record.get("rejection_reason") == rejection_reason]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(f"{json.dumps(record, sort_keys=True)}\n" for record in selected), encoding="utf-8")
    return len(selected)


def load_json_lines(input_path: Path) -> list[dict[str, Any]]:
    records = []

    for line_number, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON in {input_path} at line {line_number}") from error
        if not isinstance(record, dict):
            raise ValueError(f"Expected a JSON object in {input_path} at line {line_number}")
        records.append(record)

    return records


def build_replay_payload(record: dict[str, Any]) -> dict[str, Any]:
    required = ("observation_id", "patient_id", "loinc_code", "value", "effective_datetime")
    missing = [field for field in required if record.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Quarantine record is missing required fields: {', '.join(missing)}")

    loinc_code = str(record["loinc_code"])
    vital_name = LOINC_TO_VITAL.get(loinc_code)
    if vital_name is None:
        raise ValueError(f"Unsupported quarantine LOINC code: {loinc_code}")

    value = record["value"]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Quarantine record value must be numeric")

    return {
        "schema_version": "1.0",
        "observation_id": str(record["observation_id"]),
        "patient_id": str(record["patient_id"]),
        "source": "quarantine_replay",
        "event_timestamp": str(record["effective_datetime"]),
        vital_name: value,
    }


def publish_records(kinesis_client: Any, stream_name: str, payloads: list[dict[str, Any]]) -> int:
    published = 0

    for offset in range(0, len(payloads), 500):
        batch = payloads[offset : offset + 500]
        response = kinesis_client.put_records(
            StreamName=stream_name, Records=[{"Data": json.dumps(payload).encode("utf-8"), "PartitionKey": payload["patient_id"]} for payload in batch]
        )
        failures = [result for result in response.get("Records", []) if result.get("ErrorCode")]
        if failures:
            raise RuntimeError(f"Kinesis rejected {len(failures)} of {len(batch)} quarantine replay records")
        published += len(batch)

    return published


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and replay analytically quarantined FHIR measurements")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export quarantine records from S3 to reviewed JSONL")
    export_parser.add_argument("--bucket", required=True)
    export_parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--rejection-reason")

    replay_parser = subparsers.add_parser("replay", help="Validate and republish corrected JSONL records")
    replay_parser.add_argument("--input", type=Path, required=True)
    replay_parser.add_argument("--stream-name", required=True)
    replay_parser.add_argument("--confirm-replay", action="store_true")

    parser.add_argument("--region", default=AWS_REGION)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if not arguments.region:
        raise ValueError("Set AWS_REGION or pass --region")

    if arguments.command == "export":
        s3_client = boto3.client("s3", region_name=arguments.region)
        count = export_records(iter_quarantine_records(s3_client, arguments.bucket, arguments.prefix), arguments.output, arguments.rejection_reason)
        print(f"Exported {count} quarantine record(s) to {arguments.output}")
        return

    records = load_json_lines(arguments.input)
    payloads = [build_replay_payload(record) for record in records]
    if not arguments.confirm_replay:
        print(f"Validated {len(payloads)} corrected record(s); add --confirm-replay to publish")
        return

    kinesis_client = boto3.client("kinesis", region_name=arguments.region)
    count = publish_records(kinesis_client, arguments.stream_name, payloads)
    print(f"Published {count} corrected quarantine record(s) to {arguments.stream_name}")


if __name__ == "__main__":
    main()
