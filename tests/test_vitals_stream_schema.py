import pytest

from services.vitals_stream_processor.schema import validate_vitals_payload


def valid_payload() -> dict:
    return {
        "schema_version": "1.0",
        "patient_id": "schema-test-patient",
        "event_timestamp": "2026-08-30T20:30:00Z",
        "source": "schema_unit_test",
        "heart_rate": 80,
        "spo2": 98,
        "respiratory_rate": 16,
        "systolic_bp": 120,
        "diastolic_bp": 80,
    }


def test_valid_payload_passes() -> None:
    validate_vitals_payload(valid_payload())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("heart_rate", 19),
        ("heart_rate", 251),
        ("spo2", 49),
        ("spo2", 101),
        ("respiratory_rate", 3),
        ("respiratory_rate", 81),
        ("systolic_bp", 49),
        ("systolic_bp", 301),
        ("diastolic_bp", 19),
        ("diastolic_bp", 201),
    ],
)
def test_out_of_range_vital_fails(field: str, value: int) -> None:
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        validate_vitals_payload(payload)


def test_missing_schema_version_fails() -> None:
    payload = valid_payload()
    payload.pop("schema_version")

    with pytest.raises(ValueError, match="schema_version"):
        validate_vitals_payload(payload)


def test_unknown_schema_version_fails() -> None:
    payload = valid_payload()
    payload["schema_version"] = "2.0"

    with pytest.raises(ValueError, match="schema_version"):
        validate_vitals_payload(payload)


def test_missing_patient_id_fails() -> None:
    payload = valid_payload()
    payload.pop("patient_id")

    with pytest.raises(ValueError, match="patient_id"):
        validate_vitals_payload(payload)


def test_invalid_timestamp_fails() -> None:
    payload = valid_payload()
    payload["event_timestamp"] = "not-a-timestamp"

    with pytest.raises(ValueError, match="event_timestamp"):
        validate_vitals_payload(payload)


def test_non_numeric_vital_fails() -> None:
    payload = valid_payload()
    payload["heart_rate"] = "80"

    with pytest.raises(ValueError, match="heart_rate"):
        validate_vitals_payload(payload)


def test_payload_requires_at_least_one_vital() -> None:
    payload = valid_payload()

    for field in ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp"):
        payload.pop(field)

    with pytest.raises(ValueError, match="at least one supported vital"):
        validate_vitals_payload(payload)


def test_replay_attempt_must_be_non_negative_integer() -> None:
    payload = valid_payload()
    payload["_replay_attempt"] = -1

    with pytest.raises(ValueError, match="_replay_attempt"):
        validate_vitals_payload(payload)
