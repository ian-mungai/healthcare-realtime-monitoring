import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.quarantine.manage_quarantine import build_replay_payload, export_records, iter_quarantine_records, load_json_lines, publish_records


def quarantine_record(**overrides):
    record = {
        "observation_id": "observation-1",
        "patient_id": "patient-1",
        "loinc_code": "8867-4",
        "value": 82.0,
        "effective_datetime": "2026-09-09T12:00:00Z",
        "rejection_reason": "physiological_range_violation",
    }
    record.update(overrides)
    return record


def test_iter_and_export_quarantine_records(tmp_path: Path) -> None:
    s3_client = Mock()
    paginator = s3_client.get_paginator.return_value
    paginator.paginate.return_value = [{"Contents": [{"Key": "quarantine/fhir/part-1.json"}]}]
    body = Mock()
    body.iter_lines.return_value = [json.dumps(quarantine_record()).encode(), json.dumps(quarantine_record(rejection_reason="missing_value")).encode()]
    s3_client.get_object.return_value = {"Body": body}
    output = tmp_path / "review.jsonl"

    count = export_records(iter_quarantine_records(s3_client, "test-bucket", "quarantine/fhir/"), output, "missing_value")

    assert count == 1
    assert json.loads(output.read_text())["rejection_reason"] == "missing_value"


def test_build_replay_payload_maps_loinc_to_vital() -> None:
    payload = build_replay_payload(quarantine_record(loinc_code="8480-6", value=120.0))

    assert payload == {
        "schema_version": "1.0",
        "observation_id": "observation-1",
        "patient_id": "patient-1",
        "source": "quarantine_replay",
        "event_timestamp": "2026-09-09T12:00:00Z",
        "systolic_bp": 120.0,
    }


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (quarantine_record(patient_id=""), "missing required fields"),
        (quarantine_record(loinc_code="unknown"), "Unsupported quarantine LOINC"),
        (quarantine_record(value="82"), "must be numeric"),
    ],
)
def test_build_replay_payload_rejects_unreviewed_values(record, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_replay_payload(record)


def test_load_json_lines_reports_line_number(tmp_path: Path) -> None:
    input_path = tmp_path / "review.jsonl"
    input_path.write_text(json.dumps(quarantine_record()) + "\nnot-json\n")

    with pytest.raises(ValueError, match="line 2"):
        load_json_lines(input_path)


def test_publish_records_uses_patient_partition_key() -> None:
    client = Mock()
    client.put_records.return_value = {"Records": [{"SequenceNumber": "1"}]}
    payload = build_replay_payload(quarantine_record())

    assert publish_records(client, "test-stream", [payload]) == 1
    record = client.put_records.call_args.kwargs["Records"][0]
    assert record["PartitionKey"] == "patient-1"
    assert json.loads(record["Data"])["source"] == "quarantine_replay"


def test_publish_records_fails_on_partial_kinesis_rejection() -> None:
    client = Mock()
    client.put_records.return_value = {"Records": [{"ErrorCode": "ProvisionedThroughputExceededException"}]}

    with pytest.raises(RuntimeError, match="rejected 1"):
        publish_records(client, "test-stream", [build_replay_payload(quarantine_record())])
