import argparse
import json
import os
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import boto3
import websocket
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
STREAM_NAME = "healthcare_realtime_vitals_load_test"
RESULTS_TABLE_NAME = "healthcare-realtime-load-test-results"
PATIENT_PREFIX = "load_test_patient_"


@dataclass(frozen=True)
class BatchResult:
    successful_observation_ids: list[str]
    failed: int
    latency_ms: float


class WebSocketObserver:
    def __init__(self, base_url: str, patient_ids: list[str], region: str) -> None:
        self.base_url = base_url
        self.patient_ids = patient_ids
        self.region = region
        self.received_at: dict[str, datetime] = {}
        self.errors: list[str] = []
        self._apps: list[websocket.WebSocketApp] = []
        self._threads: list[threading.Thread] = []
        self._opened = [threading.Event() for _ in patient_ids]
        self._lock = threading.Lock()
        self._stopping = False

    def _subscription_url(self, patient_id: str) -> str:
        separator = "&" if "?" in self.base_url else "?"
        return f"{self.base_url}{separator}{urlencode({'patient_id': patient_id})}"

    def _headers(self, url: str) -> dict[str, str]:
        credentials = boto3.Session(region_name=self.region).get_credentials()

        if credentials is None:
            raise RuntimeError("AWS credentials are required for WebSocket validation")

        signing_url = "https://" + url.removeprefix("wss://")
        request = AWSRequest(method="GET", url=signing_url)
        SigV4Auth(credentials.get_frozen_credentials(), "execute-api", self.region).add_auth(request)
        return {key: str(value) for key, value in request.headers.items()}

    def start(self, timeout_seconds: float = 15.0) -> None:
        for index, patient_id in enumerate(self.patient_ids):
            url = self._subscription_url(patient_id)

            def on_open(_app: websocket.WebSocketApp, event: threading.Event = self._opened[index]) -> None:
                event.set()

            def on_message(_app: websocket.WebSocketApp, message: str) -> None:
                try:
                    payload = json.loads(message)
                    observation_id = payload.get("observation_id")
                except (json.JSONDecodeError, TypeError):
                    return

                if isinstance(observation_id, str) and payload.get("source") == "load_test":
                    with self._lock:
                        self.received_at.setdefault(observation_id, datetime.now(UTC))

            def on_error(_app: websocket.WebSocketApp, error: Any) -> None:
                if not self._stopping:
                    with self._lock:
                        self.errors.append(str(error))

            app = websocket.WebSocketApp(url, header=self._headers(url), on_open=on_open, on_message=on_message, on_error=on_error)
            thread = threading.Thread(target=app.run_forever, daemon=True)
            self._apps.append(app)
            self._threads.append(thread)
            thread.start()

        deadline = time.monotonic() + timeout_seconds

        for opened in self._opened:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not opened.wait(remaining):
                self.stop()
                detail = f": {self.errors[-1]}" if self.errors else ""
                raise RuntimeError(f"WebSocket load-test subscriptions did not connect{detail}")

    def wait_for(self, observation_ids: set[str], timeout_seconds: float) -> dict[str, datetime]:
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            with self._lock:
                received = {key: value for key, value in self.received_at.items() if key in observation_ids}

            if len(received) == len(observation_ids):
                return received

            time.sleep(0.1)

        with self._lock:
            return {key: value for key, value in self.received_at.items() if key in observation_ids}

    def stop(self) -> None:
        self._stopping = True

        for app in self._apps:
            app.close()

        for thread in self._threads:
            thread.join(timeout=2)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load test the isolated healthcare realtime pipeline")
    parser.add_argument("--patients", type=int, default=10)
    parser.add_argument("--events-per-second", type=float, default=1.0)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--stream-name", default=STREAM_NAME)
    parser.add_argument("--results-table", default=RESULTS_TABLE_NAME)
    parser.add_argument("--websocket-url", default=os.getenv("VITALS_WEBSOCKET_URL"))
    parser.add_argument("--observation-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--skip-websocket", action="store_true")
    parser.add_argument("--retain-results", action="store_true")
    parser.add_argument("--region", default=AWS_REGION)
    return parser.parse_args()


def build_payload(patient_number: int, sequence_number: int, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "observation_id": f"load-test-{run_id}-{patient_number:02d}-{sequence_number:08d}",
        "patient_id": f"{PATIENT_PREFIX}{patient_number:02d}",
        "source": "load_test",
        "event_timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "heart_rate": 70 + (sequence_number % 20),
        "spo2": 95 + (sequence_number % 5),
        "respiratory_rate": 14 + (sequence_number % 6),
        "systolic_bp": 110 + (sequence_number % 20),
        "diastolic_bp": 70 + (sequence_number % 10),
    }


def build_records(patients: int, sequence_number: int, run_id: str) -> list[dict[str, Any]]:
    records = []

    for patient_number in range(1, patients + 1):
        payload = build_payload(patient_number, sequence_number, run_id)
        records.append({"Data": json.dumps(payload).encode("utf-8"), "PartitionKey": payload["patient_id"]})

    return records


def record_payload(record: dict[str, Any]) -> dict[str, Any]:
    return json.loads(record["Data"])


def put_batch(kinesis_client: Any, stream_name: str, records: list[dict[str, Any]]) -> BatchResult:
    started = time.perf_counter()
    response = kinesis_client.put_records(StreamName=stream_name, Records=records)
    latency_ms = (time.perf_counter() - started) * 1000
    results = response.get("Records")

    if not isinstance(results, list) or len(results) != len(records):
        raise RuntimeError("Kinesis PutRecords response did not contain one result per record")

    successful_ids = [record_payload(record)["observation_id"] for record, result in zip(records, results, strict=True) if "ErrorCode" not in result]
    return BatchResult(successful_ids, len(records) - len(successful_ids), latency_ms)


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = int((len(ordered) - 1) * percentile_value)
    return ordered[index]


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def wait_for_results(dynamodb: Any, table_name: str, observation_ids: set[str], timeout_seconds: float) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline and len(found) < len(observation_ids):
        pending = sorted(observation_ids - found.keys())

        for offset in range(0, len(pending), 100):
            keys = [{"observation_id": observation_id} for observation_id in pending[offset : offset + 100]]
            response = dynamodb.batch_get_item(RequestItems={table_name: {"Keys": keys, "ConsistentRead": True}})

            for item in response.get("Responses", {}).get(table_name, []):
                found[item["observation_id"]] = item

        if len(found) < len(observation_ids):
            time.sleep(0.2)

    return found


def cleanup_results(table: Any, observation_ids: set[str]) -> None:
    with table.batch_writer() as batch:
        for observation_id in observation_ids:
            batch.delete_item(Key={"observation_id": observation_id})


def report_latencies(label: str, latencies_ms: list[float]) -> None:
    print(f"{label}:")
    print(f"  observed: {len(latencies_ms)}")

    if latencies_ms:
        print(f"  mean: {statistics.mean(latencies_ms):.2f} ms")
        print(f"  p50:  {percentile(latencies_ms, 0.50):.2f} ms")
        print(f"  p95:  {percentile(latencies_ms, 0.95):.2f} ms")
        print(f"  p99:  {percentile(latencies_ms, 0.99):.2f} ms")
        print(f"  max:  {max(latencies_ms):.2f} ms")


def run_load_test(
    patients: int,
    events_per_second: float,
    duration_seconds: int,
    stream_name: str,
    region: str,
    results_table_name: str | None = None,
    websocket_url: str | None = None,
    observation_timeout_seconds: float = 30.0,
    retain_results: bool = False,
) -> None:
    if patients <= 0:
        raise ValueError("patients must be greater than zero")
    if events_per_second <= 0:
        raise ValueError("events-per-second must be greater than zero")
    if duration_seconds <= 0:
        raise ValueError("duration-seconds must be greater than zero")
    if patients > 500:
        raise ValueError("patients must not exceed the Kinesis PutRecords limit of 500 records per request")
    if stream_name == "healthcare_realtime_vitals":
        raise ValueError("the production stream is not allowed; use the isolated load-test stream")

    kinesis_client = boto3.client("kinesis", region_name=region)
    dynamodb = boto3.resource("dynamodb", region_name=region) if results_table_name else None
    results_table = dynamodb.Table(results_table_name) if dynamodb and results_table_name else None
    patient_ids = [f"{PATIENT_PREFIX}{patient_number:02d}" for patient_number in range(1, patients + 1)]
    websocket_observer = WebSocketObserver(websocket_url, patient_ids, region) if websocket_url else None

    interval_seconds = 1 / events_per_second
    expected_event_count = int(patients * events_per_second * duration_seconds)
    successful_writes = 0
    failed_writes = 0
    batch_latencies_ms: list[float] = []
    expected_observations: dict[str, datetime] = {}
    sequence_number = 0
    run_id = uuid4().hex

    print("Healthcare Realtime Load Test")
    print(f"Run ID: {run_id}")
    print(f"Isolated stream: {stream_name}")
    print(f"Isolated results table: {results_table_name or 'not verified'}")
    print(f"Patients: {patients}")
    print(f"Events/second/patient: {events_per_second}")
    print(f"Duration: {duration_seconds} seconds")
    print(f"Expected events: approximately {expected_event_count}")
    print()

    if websocket_observer:
        websocket_observer.start()

    started = time.perf_counter()
    next_batch_time = started
    deadline = started + duration_seconds

    try:
        while next_batch_time < deadline:
            sleep_seconds = next_batch_time - time.perf_counter()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            records = build_records(patients, sequence_number, run_id)
            payloads = {record_payload(record)["observation_id"]: record_payload(record) for record in records}

            try:
                batch_result = put_batch(kinesis_client, stream_name, records)
                successful_writes += len(batch_result.successful_observation_ids)
                failed_writes += batch_result.failed
                batch_latencies_ms.append(batch_result.latency_ms)

                for observation_id in batch_result.successful_observation_ids:
                    expected_observations[observation_id] = parse_timestamp(payloads[observation_id]["event_timestamp"])
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
            report_latencies("Kinesis PutRecords batch request latency", batch_latencies_ms)

        expected_ids = set(expected_observations)
        missing_results: set[str] = set()
        missing_websocket: set[str] = set()

        if dynamodb and results_table_name:
            results = wait_for_results(dynamodb, results_table_name, expected_ids, observation_timeout_seconds)
            missing_results = expected_ids - results.keys()
            processing_latencies = [
                (parse_timestamp(item["processed_at"]) - expected_observations[observation_id]).total_seconds() * 1000
                for observation_id, item in results.items()
            ]
            print()
            report_latencies("Kinesis-to-DynamoDB processing latency", processing_latencies)
            print(f"  missing: {len(missing_results)}")

        if websocket_observer:
            received = websocket_observer.wait_for(expected_ids, observation_timeout_seconds)
            missing_websocket = expected_ids - received.keys()
            delivery_latencies = [
                (received_at - expected_observations[observation_id]).total_seconds() * 1000 for observation_id, received_at in received.items()
            ]
            print()
            report_latencies("Kinesis-to-WebSocket delivery latency", delivery_latencies)
            print(f"  missing: {len(missing_websocket)}")

        if failed_writes or missing_results or missing_websocket:
            raise RuntimeError(
                "load test failed: "
                f"{failed_writes} producer writes failed, "
                f"{len(missing_results)} DynamoDB observations missing, and "
                f"{len(missing_websocket)} WebSocket observations missing"
            )
    finally:
        if websocket_observer:
            websocket_observer.stop()
        if results_table and expected_observations and not retain_results:
            cleanup_results(results_table, set(expected_observations))


def main() -> None:
    arguments = parse_arguments()

    if not arguments.region:
        raise ValueError("set AWS_REGION or pass --region")
    if not arguments.websocket_url and not arguments.skip_websocket:
        raise ValueError("set VITALS_WEBSOCKET_URL, pass --websocket-url, or explicitly use --skip-websocket")

    run_load_test(
        patients=arguments.patients,
        events_per_second=arguments.events_per_second,
        duration_seconds=arguments.duration_seconds,
        stream_name=arguments.stream_name,
        region=arguments.region,
        results_table_name=arguments.results_table,
        websocket_url=None if arguments.skip_websocket else arguments.websocket_url,
        observation_timeout_seconds=arguments.observation_timeout_seconds,
        retain_results=arguments.retain_results,
    )


if __name__ == "__main__":
    main()
