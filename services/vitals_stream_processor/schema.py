from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "1.0"

VITAL_RANGES: dict[str, tuple[float, float]] = {
    "heart_rate": (20, 250),
    "spo2": (50, 100),
    "respiratory_rate": (4, 80),
    "systolic_bp": (50, 300),
    "diastolic_bp": (20, 200),
}


def validate_event_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("event_timestamp must be a non-empty ISO-8601 string")

    try:
        event_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"event_timestamp is not valid ISO-8601: {value!r}") from error

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)


def validate_numeric_vital(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be numeric")

    minimum, maximum = VITAL_RANGES[name]

    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")


def validate_vitals_payload(payload: dict[str, Any]) -> None:
    schema_version = payload.get("schema_version")

    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")

    patient_id = payload.get("patient_id")

    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("patient_id must be a non-empty string")

    source = payload.get("source")

    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")

    validate_event_timestamp(payload.get("event_timestamp"))

    present_vitals = 0

    for vital_name in VITAL_RANGES:
        if vital_name not in payload:
            continue

        present_vitals += 1
        validate_numeric_vital(vital_name, payload[vital_name])

    if present_vitals == 0:
        raise ValueError("at least one supported vital measurement is required")

    replay_attempt = payload.get("_replay_attempt")

    if replay_attempt is not None and (isinstance(replay_attempt, bool) or not isinstance(replay_attempt, int) or replay_attempt < 0):
        raise ValueError("_replay_attempt must be a non-negative integer")
