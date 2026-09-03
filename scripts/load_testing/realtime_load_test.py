import argparse
import json
import os
import statistics
import time
from datetime import UTC, datetime
from typing import Any

import boto3

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
STREAM_NAME = "healthcare_realtime_vitals"
PATIENT_PREFIX = "load_test_patient_"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load test the healthcare realtime Kinesis pipeline")
    parser.add_argument("--patients", type=int, default=10)
    parser.add_argument("--events-per-second", type=float, default=1.0)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--stream-name", default=STREAM_NAME)
    parser.add_argument("--region", default=AWS_REGION)
    return parser.parse_args()


def build_payload(patient_number: int, sequence_number: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "patient_id": f"{PATIENT_PREFIX}{patient_number:02d}",
        "source": "load_test",
        "event_timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "heart_rate": 70 + (sequence_number % 20),
        "spo2": 95 + (sequence_number % 5),
        "respiratory_rate": 14 + (sequence_number % 6),
        "systolic_bp": 110 + (sequence_number % 20),
        "diastolic_bp": 70 + (sequence_number % 10),
    }


def build_records(patients: int, sequence_number: int) -> list[dict[str, Any]]:
    records = []

    for patient_number in range(1, patients + 1):
        payload = build_payload(patient_number, sequence_number)

        records.append({"Data": json.dumps(payload).encode("utf-8"), "PartitionKey": payload["patient_id"]})

    return records


def put_batch(kinesis_client: Any, stream_name: str, records: list[dict[str, Any]]) -> tuple[int, int, float]:
    started = time.perf_counter()

    response = kinesis_client.put_records(StreamName=stream_name, Records=records)

    latency_ms = (time.perf_counter() - started) * 1000

    failed = response.get("FailedRecordCount", 0)
    successful = len(records) - failed

    return successful, failed, latency_ms


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = int((len(ordered) - 1) * percentile_value)
    return ordered[index]


def run_load_test(patients: int, events_per_second: float, duration_seconds: int, stream_name: str, region: str) -> None:
    if patients <= 0:
        raise ValueError("patients must be greater than zero")

    if events_per_second <= 0:
        raise ValueError("events-per-second must be greater than zero")

    if duration_seconds <= 0:
        raise ValueError("duration-seconds must be greater than zero")

    if patients > 500:
        raise ValueError("patients must not exceed the Kinesis PutRecords limit of 500 records per request")

    kinesis_client = boto3.client("kinesis", region_name=region)

    interval_seconds = 1 / events_per_second
    expected_events = int(patients * events_per_second * duration_seconds)

    successful_writes = 0
    failed_writes = 0
    batch_latencies_ms: list[float] = []
    sequence_number = 0

    print("Healthcare Realtime Load Test")
    print(f"Stream: {stream_name}")
    print(f"Patients: {patients}")
    print(f"Events/second/patient: {events_per_second}")
    print(f"Duration: {duration_seconds} seconds")
    print(f"Expected events: approximately {expected_events}")
    print()

    started = time.perf_counter()
    next_batch_time = started
    deadline = started + duration_seconds

    while next_batch_time < deadline:
        sleep_seconds = next_batch_time - time.perf_counter()

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        records = build_records(patients, sequence_number)

        try:
            successful, failed, latency_ms = put_batch(kinesis_client, stream_name, records)

            successful_writes += successful
            failed_writes += failed
            batch_latencies_ms.append(latency_ms)

        except Exception as error:
            failed_writes += len(records)
            print(f"Batch {sequence_number} failed: {error}")

        sequence_number += 1
        next_batch_time = started + (sequence_number * interval_seconds)

    elapsed_seconds = time.perf_counter() - started
    total_attempted = successful_writes + failed_writes
    achieved_rate = successful_writes / elapsed_seconds if elapsed_seconds else 0
    success_rate = successful_writes / total_attempted * 100 if total_attempted else 0

    print()
    print("=== LOAD TEST RESULTS ===")
    print(f"Attempted writes: {total_attempted}")
    print(f"Successful writes: {successful_writes}")
    print(f"Failed writes: {failed_writes}")
    print(f"Success rate: {success_rate:.2f}%")
    print(f"Elapsed seconds: {elapsed_seconds:.2f}")
    print(f"Achieved total event rate: {achieved_rate:.2f} events/second")

    if batch_latencies_ms:
        print()
        print("Kinesis PutRecords batch request latency:")
        print(f"  mean: {statistics.mean(batch_latencies_ms):.2f} ms")
        print(f"  p50:  {percentile(batch_latencies_ms, 0.50):.2f} ms")
        print(f"  p95:  {percentile(batch_latencies_ms, 0.95):.2f} ms")
        print(f"  p99:  {percentile(batch_latencies_ms, 0.99):.2f} ms")
        print(f"  max:  {max(batch_latencies_ms):.2f} ms")


def main() -> None:
    arguments = parse_arguments()

    run_load_test(
        patients=arguments.patients,
        events_per_second=arguments.events_per_second,
        duration_seconds=arguments.duration_seconds,
        stream_name=arguments.stream_name,
        region=arguments.region,
    )


if __name__ == "__main__":
    main()
