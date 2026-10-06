import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import boto3
import websocket
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError

from scripts.synthea_loader.src.cohort import cohort_patient_ids
from tools.process import run_command

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
STREAM_NAME = os.getenv("LOAD_TEST_KINESIS_STREAM_NAME")
PRIMARY_STREAM_NAME = os.getenv("KINESIS_STREAM_NAME") or ""
RESULTS_TABLE_NAME = os.getenv("LOAD_TEST_RESULTS_TABLE")
PATIENT_PREFIX = "load_test_patient_"
# Total time to close every subscription; one shared deadline, so ten slow receivers cannot take ten times as long.
WEBSOCKET_STOP_TIMEOUT_SECONDS = 10.0
DEFAULT_ARTIFACT_DIR = Path("artifacts/e2e/load_test")
DEFAULT_PATIENT_MAP = Path(__file__).resolve().parents[2] / "scripts/synthea_loader/state/fhir_resource_map.json"


class LoadTestError(Exception):
    """A failure with a fixed category and an identifier-free message, safe to record in the run artifact."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class LoadTestInputError(LoadTestError, ValueError):
    """Invalid configuration or cohort selection, raised before any event is sent."""


class LoadTestCheckError(LoadTestError, RuntimeError):
    """A runtime check failed: WebSocket access, producer response, delivery or cleanup."""


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
            raise LoadTestCheckError("websocket access", "AWS credentials are required for WebSocket validation")

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
                    status = getattr(error, "status_code", None)
                    with self._lock:
                        self.errors.append(f"HTTP {status}" if isinstance(status, int) else type(error).__name__)

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
                with self._lock:
                    causes = ", ".join(sorted(set(self.errors))) or "timed out"
                raise LoadTestCheckError("websocket access", f"subscriptions did not connect ({causes}); check the signing identity and cohort access policy")

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
        cleanup_failed = False

        for app in self._apps:
            try:
                app.close()
            except Exception:
                cleanup_failed = True

        deadline = time.monotonic() + WEBSOCKET_STOP_TIMEOUT_SECONDS
        for thread in self._threads:
            try:
                thread.join(timeout=max(deadline - time.monotonic(), 0.0))
                cleanup_failed = thread.is_alive() or cleanup_failed
            except RuntimeError:
                cleanup_failed = True
        if cleanup_failed:
            raise LoadTestCheckError("cleanup", "not all load-test WebSocket connections and receiver threads were closed")


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
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR, help="Folder for the run's JSON and Markdown evidence")
    parser.add_argument(
        "--patient-map", type=Path, default=Path(os.getenv("FHIR_RESOURCE_MAP_FILE") or DEFAULT_PATIENT_MAP), help="Generated ten-patient FHIR map"
    )
    return parser.parse_args()


def load_patient_selection(path: Path, count: int) -> tuple[list[str], str]:
    """Select synthetic cohort patients and fingerprint the unchanged input map without reporting its identifiers."""
    try:
        before = path.read_bytes()
        patient_ids = list(cohort_patient_ids(path))
    except FileNotFoundError:
        raise LoadTestInputError("cohort map", "the generated ten-patient map was not found; pass --patient-map or set FHIR_RESOURCE_MAP_FILE") from None
    except (OSError, ValueError, AttributeError):
        raise LoadTestInputError("cohort map", "the map is unreadable or does not list ten unique cohort patients") from None
    if count <= 0 or count > len(patient_ids):
        raise LoadTestInputError(
            "configuration", "patients must be between one and the ten authorized cohort patients; increase the event rate for higher load"
        )
    if path.read_bytes() != before:
        raise LoadTestInputError("cohort map", "the cohort map changed while selecting patients; select the deployment's stable map")
    return patient_ids[:count], hashlib.sha256(before).hexdigest()


def build_payload(patient_number: int, sequence_number: int, run_id: str, patient_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "observation_id": f"load-test-{run_id}-{patient_number:02d}-{sequence_number:08d}",
        "patient_id": patient_id if patient_id is not None else f"{PATIENT_PREFIX}{patient_number:02d}",
        "source": "load_test",
        "event_timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "heart_rate": 70 + (sequence_number % 20),
        "spo2": 95 + (sequence_number % 5),
        "respiratory_rate": 14 + (sequence_number % 6),
        "systolic_bp": 110 + (sequence_number % 20),
        "diastolic_bp": 70 + (sequence_number % 10),
    }


def build_records(patients: int, sequence_number: int, run_id: str, patient_ids: list[str] | None = None) -> list[dict[str, Any]]:
    records = []

    for patient_number in range(1, patients + 1):
        patient_id = patient_ids[patient_number - 1] if patient_ids is not None else None
        payload = build_payload(patient_number, sequence_number, run_id, patient_id)
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
        raise LoadTestCheckError("producer", "Kinesis PutRecords response did not contain one result per record")

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


def latency_summary(latencies_ms: list[float]) -> dict[str, float | int]:
    """Summarize latencies in milliseconds for the run artifact."""
    if not latencies_ms:
        return {"observed": 0}
    return {
        "observed": len(latencies_ms),
        "mean_ms": round(statistics.mean(latencies_ms), 2),
        "p50_ms": round(percentile(latencies_ms, 0.50), 2),
        "p95_ms": round(percentile(latencies_ms, 0.95), 2),
        "p99_ms": round(percentile(latencies_ms, 0.99), 2),
        "max_ms": round(max(latencies_ms), 2),
    }


def report_latencies(label: str, latencies_ms: list[float]) -> None:
    sys.stdout.write(f"{label}:\n")
    sys.stdout.write(f"  observed: {len(latencies_ms)}\n")

    if latencies_ms:
        sys.stdout.write(f"  mean: {statistics.mean(latencies_ms):.2f} ms\n")
        sys.stdout.write(f"  p50:  {percentile(latencies_ms, 0.50):.2f} ms\n")
        sys.stdout.write(f"  p95:  {percentile(latencies_ms, 0.95):.2f} ms\n")
        sys.stdout.write(f"  p99:  {percentile(latencies_ms, 0.99):.2f} ms\n")
        sys.stdout.write(f"  max:  {max(latencies_ms):.2f} ms\n")


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
    summary: dict[str, Any] | None = None,
    patient_ids: list[str] | None = None,
) -> None:
    if patients <= 0:
        raise LoadTestInputError("configuration", "patients must be greater than zero")
    if not math.isfinite(events_per_second) or events_per_second <= 0:
        raise LoadTestInputError("configuration", "events-per-second must be greater than zero")
    if duration_seconds <= 0:
        raise LoadTestInputError("configuration", "duration-seconds must be greater than zero")
    if patients > 500:
        raise LoadTestInputError("configuration", "patients must not exceed the Kinesis PutRecords limit of 500 records per request")
    if not math.isfinite(observation_timeout_seconds) or observation_timeout_seconds <= 0:
        raise LoadTestInputError("configuration", "observation timeout must be finite and greater than zero")
    if not PRIMARY_STREAM_NAME or not stream_name:
        raise LoadTestInputError("configuration", "set the main and isolated Kinesis stream names before starting a load test")
    if stream_name == PRIMARY_STREAM_NAME:
        raise LoadTestInputError("configuration", "the production stream is not allowed; use the isolated load-test stream")
    if patient_ids is not None and (len(patient_ids) != patients or len(set(patient_ids)) != patients or any(not value.strip() for value in patient_ids)):
        raise LoadTestInputError("configuration", "patient selection must contain one unique non-empty cohort identifier per requested patient")
    if websocket_url and patient_ids is None:
        raise LoadTestInputError("configuration", "WebSocket verification requires an explicit authorized cohort selection")

    kinesis_client = boto3.client("kinesis", region_name=region)
    dynamodb = boto3.resource("dynamodb", region_name=region) if results_table_name else None
    results_table = dynamodb.Table(results_table_name) if dynamodb and results_table_name else None
    selected_patients = patient_ids or [f"{PATIENT_PREFIX}{patient_number:02d}" for patient_number in range(1, patients + 1)]
    websocket_observer = WebSocketObserver(websocket_url, selected_patients, region) if websocket_url else None

    interval_seconds = 1 / events_per_second
    expected_event_count = int(patients * events_per_second * duration_seconds)
    successful_writes = 0
    failed_writes = 0
    batch_latencies_ms: list[float] = []
    expected_observations: dict[str, datetime] = {}
    sequence_number = 0
    results: dict[str, Any] = summary if summary is not None else {}
    run_id = str(results.get("run_id") or uuid4().hex)
    results["run_id"] = run_id

    sys.stdout.write("Healthcare Realtime Load Test\n")
    sys.stdout.write(f"Run ID: {run_id}\n")
    sys.stdout.write("Stream: isolated load-test lane\n")
    sys.stdout.write(f"Results table check: {'enabled' if results_table_name else 'skipped'}\n")
    sys.stdout.write(f"Patients: {patients}\n")
    sys.stdout.write(f"Events/second/patient: {events_per_second}\n")
    sys.stdout.write(f"Duration: {duration_seconds} seconds\n")
    sys.stdout.write(f"Expected events: approximately {expected_event_count}\n")
    sys.stdout.write("\n")

    run_error: BaseException | None = None
    try:
        if websocket_observer:
            websocket_observer.start()
        started = time.perf_counter()
        next_batch_time = started
        deadline = started + duration_seconds
        while next_batch_time < deadline:
            sleep_seconds = next_batch_time - time.perf_counter()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            records = build_records(patients, sequence_number, run_id, selected_patients)
            payloads = {record_payload(record)["observation_id"]: record_payload(record) for record in records}

            try:
                batch_result = put_batch(kinesis_client, stream_name, records)
                successful_writes += len(batch_result.successful_observation_ids)
                failed_writes += batch_result.failed
                batch_latencies_ms.append(batch_result.latency_ms)

                for observation_id in batch_result.successful_observation_ids:
                    expected_observations[observation_id] = parse_timestamp(payloads[observation_id]["event_timestamp"])
            except Exception:
                failed_writes += len(records)
                sys.stdout.write(f"Batch {sequence_number} failed: producer request failed\n")

            sequence_number += 1
            next_batch_time = started + (sequence_number * interval_seconds)

        elapsed_seconds = time.perf_counter() - started
        total_attempted = successful_writes + failed_writes
        achieved_rate = successful_writes / elapsed_seconds if elapsed_seconds else 0
        success_rate = successful_writes / total_attempted * 100 if total_attempted else 0

        sys.stdout.write("\n")
        sys.stdout.write("=== LOAD TEST RESULTS ===\n")
        sys.stdout.write(f"Attempted writes: {total_attempted}\n")
        sys.stdout.write(f"Successful writes: {successful_writes}\n")
        sys.stdout.write(f"Failed writes: {failed_writes}\n")
        sys.stdout.write(f"Success rate: {success_rate:.2f}%\n")
        sys.stdout.write(f"Elapsed seconds: {elapsed_seconds:.2f}\n")
        sys.stdout.write(f"Achieved total event rate: {achieved_rate:.2f} events/second\n")

        if batch_latencies_ms:
            sys.stdout.write("\n")
            report_latencies("Kinesis PutRecords batch request latency", batch_latencies_ms)
        results["producer"] = {
            "attempted_writes": total_attempted,
            "successful_writes": successful_writes,
            "failed_writes": failed_writes,
            "success_rate_percent": round(success_rate, 2),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "achieved_events_per_second": round(achieved_rate, 2),
            "put_records_latency": latency_summary(batch_latencies_ms),
        }

        expected_ids = set(expected_observations)
        missing_results: set[str] = set()
        missing_websocket: set[str] = set()

        if dynamodb and results_table_name:
            observed_results = wait_for_results(dynamodb, results_table_name, expected_ids, observation_timeout_seconds)
            missing_results = expected_ids - observed_results.keys()
            processing_latencies = [
                (parse_timestamp(item["processed_at"]) - expected_observations[observation_id]).total_seconds() * 1000
                for observation_id, item in observed_results.items()
            ]
            sys.stdout.write("\n")
            report_latencies("Kinesis-to-DynamoDB processing latency", processing_latencies)
            sys.stdout.write(f"  missing: {len(missing_results)}\n")
            results["dynamodb"] = {**latency_summary(processing_latencies), "missing": len(missing_results)}

        if websocket_observer:
            received = websocket_observer.wait_for(expected_ids, observation_timeout_seconds)
            missing_websocket = expected_ids - received.keys()
            delivery_latencies = [
                (received_at - expected_observations[observation_id]).total_seconds() * 1000 for observation_id, received_at in received.items()
            ]
            sys.stdout.write("\n")
            report_latencies("Kinesis-to-WebSocket delivery latency", delivery_latencies)
            sys.stdout.write(f"  missing: {len(missing_websocket)}\n")
            results["websocket"] = {**latency_summary(delivery_latencies), "missing": len(missing_websocket)}

        if not successful_writes or failed_writes or missing_results or missing_websocket:
            raise LoadTestCheckError(
                "producer" if failed_writes or not successful_writes else "delivery",
                "load test failed: "
                f"{failed_writes} producer writes failed, "
                f"{len(missing_results)} DynamoDB observations missing, and "
                f"{len(missing_websocket)} WebSocket observations missing",
            )
    except BaseException as error:
        run_error = error
        raise
    finally:
        # A cleanup failure is recorded, but it never replaces the error that already ended the run.
        try:
            if websocket_observer:
                try:
                    websocket_observer.stop()
                except LoadTestCheckError:
                    results["websocket_cleanup"] = "incomplete"
                    if run_error is None:
                        raise
        finally:
            if results_table and expected_observations and not retain_results:
                try:
                    cleanup_results(results_table, set(expected_observations))
                except Exception:
                    results["results_cleanup"] = "incomplete; DynamoDB TTL removes the rows within 24 hours"
                    if run_error is None:
                        raise


def git_revision() -> str:
    """Return the checked-out commit and whether tracked files had uncommitted changes."""
    commit = run_command("git", ["rev-parse", "HEAD"]).stdout.strip() or "unknown"
    dirty = bool(run_command("git", ["status", "--porcelain", "--untracked-files=no"]).stdout.strip())
    return f"{commit}{' with uncommitted changes' if dirty else ''}"


def write_artifact(artifact_dir: Path, report: dict[str, Any]) -> Path:
    """Write the run's JSON and Markdown evidence; deployment endpoints are never recorded."""
    run_dir = artifact_dir / f"{report['started_at_utc'].replace(':', '').replace('-', '')}_{str(report.get('run_id', 'not-started'))[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    websocket_result = report.get("websocket") or {}
    delivery = "skipped" if not report["parameters"]["websocket_checked"] else "not verified"
    accepted = (report.get("producer") or {}).get("successful_writes", 0)
    if (
        report["parameters"]["websocket_checked"]
        and report["status"] == "pass"
        and accepted > 0
        and websocket_result.get("observed") == accepted
        and websocket_result.get("missing") == 0
    ):
        delivery = "verified"
    lines = [
        "# Realtime Load Test Report",
        "",
        f"- Status: {report['status']}",
        f"- Started (UTC): {report['started_at_utc']}",
        f"- Finished (UTC): {report['finished_at_utc']}",
        f"- Code revision: {report['code_revision']}",
        f"- Parameters: {json.dumps(report['parameters'], sort_keys=True)}",
        f"- WebSocket delivery: {delivery}",
        "",
        "## Results",
        "",
        "```json",
        json.dumps({key: report.get(key) for key in ("producer", "dynamodb", "websocket")}, indent=2, sort_keys=True),
        "```",
        "",
        "## Reproduce",
        "",
        "Follow docs/load-testing.md with the parameters above against a deployed environment.",
        "",
        "## Limits",
        "",
        report["limits"],
    ]
    if report.get("error"):
        lines[3:3] = [f"- Error: {report['error']}"]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


def record_failure(report: dict[str, Any], category: str, message: str) -> None:
    """Record a failed run with its fixed category; messages never include identifiers or deployment names."""
    report["status"] = "fail"
    report["error_category"] = category
    report["error"] = f"{category}: {message}"
    sys.stderr.write(f"Load test failed ({category}); review the sanitized artifact and service logs.\n")


def main() -> int:
    arguments = parse_arguments()

    report: dict[str, Any] = {
        "run_id": uuid4().hex,
        "started_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_revision": git_revision(),
        "parameters": {
            "patients": arguments.patients,
            "events_per_second": arguments.events_per_second if math.isfinite(arguments.events_per_second) else None,
            "duration_seconds": arguments.duration_seconds,
            "observation_timeout_seconds": arguments.observation_timeout_seconds if math.isfinite(arguments.observation_timeout_seconds) else None,
            "lane": "isolated load-test stream and results table",
            "patient_selection": "generated synthetic cohort",
            "websocket_checked": not arguments.skip_websocket,
        },
        "limits": "Synthetic load-test events on the isolated stream only; they never reach Firehose, S3 or the analytical path. "
        "Latency depends on the deployed environment and time of day.",
    }
    try:
        if not arguments.region:
            raise LoadTestInputError("configuration", "set AWS_REGION or pass --region")
        if not arguments.stream_name or not arguments.results_table:
            raise LoadTestInputError("configuration", "set the isolated stream and results table names or supply their CLI flags")
        if not arguments.websocket_url and not arguments.skip_websocket:
            raise LoadTestInputError("configuration", "set VITALS_WEBSOCKET_URL, pass --websocket-url, or explicitly use --skip-websocket")
        patient_ids, map_hash = load_patient_selection(arguments.patient_map, arguments.patients)
        report["patient_map_sha256"] = map_hash
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
            summary=report,
            patient_ids=patient_ids,
        )
        report["status"] = "pass"
    except LoadTestError as error:
        record_failure(report, error.category, str(error))
    except ClientError as error:
        # AWS error codes are fixed names; the message can carry resource names, so it is not recorded.
        record_failure(report, "aws request", f"{error.response.get('Error', {}).get('Code', 'unknown')}; review the access policy and service logs")
    except Exception as error:
        record_failure(report, "unexpected", f"{type(error).__name__}; review the service logs")
    finally:
        report["finished_at_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_dir = write_artifact(arguments.artifact_dir, report)
        sys.stdout.write(f"\nE2E artifact: {run_dir}\n")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
