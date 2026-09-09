import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

import pytest

from scripts.load_testing import realtime_load_test
from scripts.load_testing.realtime_load_test import build_payload, build_records
from services.vitals_stream_processor.schema import validate_vitals_payload


def test_load_test_payload_passes_stream_validation() -> None:
    payload = build_payload(patient_number=3, sequence_number=42, run_id="test-run")

    validate_vitals_payload(payload)

    assert payload["observation_id"] == "load-test-test-run-03-00000042"


def test_load_test_observation_ids_are_unique_and_repeatable() -> None:
    first_batch = build_records(patients=3, sequence_number=7, run_id="test-run")
    repeated_batch = build_records(patients=3, sequence_number=7, run_id="test-run")
    next_batch = build_records(patients=3, sequence_number=8, run_id="test-run")

    first_ids = [json.loads(record["Data"])["observation_id"] for record in first_batch]
    repeated_ids = [json.loads(record["Data"])["observation_id"] for record in repeated_batch]
    next_ids = [json.loads(record["Data"])["observation_id"] for record in next_batch]

    assert len(first_ids) == len(set(first_ids))
    assert repeated_ids == first_ids
    assert set(first_ids).isdisjoint(next_ids)


def test_percentile_handles_empty_and_ordered_values() -> None:
    assert realtime_load_test.percentile([], 0.95) == 0
    assert realtime_load_test.percentile([40, 10, 30, 20], 0.50) == 20
    assert realtime_load_test.percentile([40, 10, 30, 20], 0.95) == 30


def test_put_batch_reports_success_failures_and_latency(monkeypatch) -> None:
    client = Mock()
    client.put_records.return_value = {"FailedRecordCount": 1, "Records": [{"SequenceNumber": "1"}, {"ErrorCode": "ProvisionedThroughputExceededException"}]}
    clock = iter([10.0, 10.025])
    monkeypatch.setattr(realtime_load_test.time, "perf_counter", lambda: next(clock))
    records = build_records(2, 1, "test-run")

    result = realtime_load_test.put_batch(client, "test-stream", records)

    assert result.successful_observation_ids == ["load-test-test-run-01-00000001"]
    assert result.failed == 1
    assert result.latency_ms == pytest.approx(25)


def test_put_batch_rejects_incomplete_kinesis_response(monkeypatch) -> None:
    client = Mock()
    client.put_records.return_value = {"FailedRecordCount": 0}
    clock = iter([10.0, 10.01])
    monkeypatch.setattr(realtime_load_test.time, "perf_counter", lambda: next(clock))

    with pytest.raises(RuntimeError, match="one result per record"):
        realtime_load_test.put_batch(client, "test-stream", build_records(1, 1, "test-run"))


@pytest.mark.parametrize(
    ("patients", "rate", "duration", "message"),
    [(0, 1, 1, "patients"), (1, 0, 1, "events-per-second"), (1, 1, 0, "duration-seconds"), (501, 1, 1, "500 records")],
)
def test_run_load_test_rejects_invalid_parameters(patients, rate, duration, message) -> None:
    with pytest.raises(ValueError, match=message):
        realtime_load_test.run_load_test(patients, rate, duration, "test-stream", "example-region-1")


def test_run_load_test_rejects_production_stream() -> None:
    with pytest.raises(ValueError, match="production stream is not allowed"):
        realtime_load_test.run_load_test(1, 1, 1, "healthcare_realtime_vitals", "example-region-1")


def test_run_load_test_reports_successful_batch(monkeypatch, capsys) -> None:
    monkeypatch.setattr(realtime_load_test.boto3, "client", Mock())
    monkeypatch.setattr(
        realtime_load_test, "put_batch", Mock(return_value=realtime_load_test.BatchResult(["load-test-run-01-00000000", "load-test-run-02-00000000"], 0, 12.5))
    )
    monkeypatch.setattr(realtime_load_test, "uuid4", Mock(return_value=Mock(hex="run")))
    clock = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(realtime_load_test.time, "perf_counter", lambda: next(clock))

    realtime_load_test.run_load_test(2, 1, 1, "test-stream", "example-region-1")

    output = capsys.readouterr().out
    assert "Successful writes: 2" in output
    assert "Success rate: 100.00%" in output
    assert "mean: 12.50 ms" in output


def test_run_load_test_counts_failed_batch(monkeypatch, capsys) -> None:
    monkeypatch.setattr(realtime_load_test.boto3, "client", Mock())
    monkeypatch.setattr(realtime_load_test, "put_batch", Mock(side_effect=RuntimeError("throttled")))
    clock = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(realtime_load_test.time, "perf_counter", lambda: next(clock))

    with pytest.raises(RuntimeError, match="2 producer writes failed"):
        realtime_load_test.run_load_test(2, 1, 1, "test-stream", "example-region-1")

    output = capsys.readouterr().out
    assert "Batch 0 failed: throttled" in output
    assert "Failed writes: 2" in output
    assert "Success rate: 0.00%" in output


def test_wait_for_results_polls_until_observations_arrive(monkeypatch) -> None:
    dynamodb = Mock()
    dynamodb.batch_get_item.side_effect = [
        {"Responses": {"test-results": [{"observation_id": "one"}]}},
        {"Responses": {"test-results": [{"observation_id": "two"}]}},
    ]
    clock = iter([0.0, 0.0, 0.1, 0.2])
    monkeypatch.setattr(realtime_load_test.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(realtime_load_test.time, "sleep", Mock())

    results = realtime_load_test.wait_for_results(dynamodb, "test-results", {"one", "two"}, 1)

    assert set(results) == {"one", "two"}
    assert dynamodb.batch_get_item.call_count == 2


def test_cleanup_results_deletes_only_current_run_observations() -> None:
    table = Mock()
    writer = MagicMock()
    batch = MagicMock()
    writer.__enter__.return_value = batch
    table.batch_writer.return_value = writer

    realtime_load_test.cleanup_results(table, {"run-one", "run-two"})

    assert batch.delete_item.call_count == 2
    batch.delete_item.assert_any_call(Key={"observation_id": "run-one"})
    batch.delete_item.assert_any_call(Key={"observation_id": "run-two"})


def test_websocket_observer_builds_patient_subscription_and_filters_results(monkeypatch) -> None:
    observer = realtime_load_test.WebSocketObserver("wss://websocket.example.com/development?mode=test", ["load_test_patient_01"], "example-region-1")
    observer.received_at = {"expected": datetime(2026, 9, 9, tzinfo=UTC), "other": datetime(2026, 9, 9, tzinfo=UTC)}
    monkeypatch.setattr(realtime_load_test.time, "monotonic", lambda: 0.0)

    assert observer._subscription_url("load_test_patient_01").endswith("mode=test&patient_id=load_test_patient_01")
    assert observer.wait_for({"expected"}, 1) == {"expected": datetime(2026, 9, 9, tzinfo=UTC)}
    observer.stop()


def test_report_latencies_prints_end_to_end_percentiles(capsys) -> None:
    realtime_load_test.report_latencies("End-to-end latency", [10.0, 20.0, 30.0])

    output = capsys.readouterr().out
    assert "observed: 3" in output
    assert "mean: 20.00 ms" in output
    assert "p95:  20.00 ms" in output
    assert "max:  30.00 ms" in output


def test_parse_timestamp_accepts_utc_z_suffix() -> None:
    assert realtime_load_test.parse_timestamp("2026-09-09T12:00:00Z") == datetime(2026, 9, 9, 12, tzinfo=UTC)
