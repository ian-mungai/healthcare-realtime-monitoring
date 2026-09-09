import json
from unittest.mock import Mock

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
    client.put_records.return_value = {"FailedRecordCount": 1}
    clock = iter([10.0, 10.025])
    monkeypatch.setattr(realtime_load_test.time, "perf_counter", lambda: next(clock))

    successful, failed, latency_ms = realtime_load_test.put_batch(client, "test-stream", [{"Data": b"one"}, {"Data": b"two"}])

    assert (successful, failed) == (1, 1)
    assert latency_ms == pytest.approx(25)


@pytest.mark.parametrize(
    ("patients", "rate", "duration", "message"),
    [(0, 1, 1, "patients"), (1, 0, 1, "events-per-second"), (1, 1, 0, "duration-seconds"), (501, 1, 1, "500 records")],
)
def test_run_load_test_rejects_invalid_parameters(patients, rate, duration, message) -> None:
    with pytest.raises(ValueError, match=message):
        realtime_load_test.run_load_test(patients, rate, duration, "test-stream", "example-region-1")


def test_run_load_test_reports_successful_batch(monkeypatch, capsys) -> None:
    monkeypatch.setattr(realtime_load_test.boto3, "client", Mock())
    monkeypatch.setattr(realtime_load_test, "put_batch", Mock(return_value=(2, 0, 12.5)))
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

    realtime_load_test.run_load_test(2, 1, 1, "test-stream", "example-region-1")

    output = capsys.readouterr().out
    assert "Batch 0 failed: throttled" in output
    assert "Failed writes: 2" in output
    assert "Success rate: 0.00%" in output
