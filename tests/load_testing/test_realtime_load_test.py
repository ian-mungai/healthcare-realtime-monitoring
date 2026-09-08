import json

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
