from datetime import UTC, datetime
from importlib import import_module
from typing import Any

try:
    vital_signs = import_module("services.vital_signs")
except ModuleNotFoundError:
    vital_signs = import_module("vital_signs")

SCHEMA_VERSION = "1.0"

VITAL_RANGES: dict[str, tuple[float, float]] = vital_signs.REALTIME_VITAL_RANGES


class PermanentRecordError(ValueError):
    """Raised when retrying a malformed source record cannot succeed."""


def validate_event_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PermanentRecordError("event_timestamp must be a non-empty ISO-8601 string")

    try:
        event_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PermanentRecordError(f"event_timestamp is not valid ISO-8601: {value!r}") from error

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)


def validate_numeric_vital(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PermanentRecordError(f"{name} must be numeric")

    minimum, maximum = VITAL_RANGES[name]

    if not minimum <= value <= maximum:
        raise PermanentRecordError(f"{name} must be between {minimum:g} and {maximum:g}")


def validate_vitals_payload(payload: dict[str, Any]) -> None:
    schema_version = payload.get("schema_version")

    if schema_version != SCHEMA_VERSION:
        raise PermanentRecordError(f"schema_version must be {SCHEMA_VERSION}")

    observation_id = payload.get("observation_id")

    if not isinstance(observation_id, str) or not observation_id.strip():
        raise PermanentRecordError("observation_id must be a non-empty string")

    patient_id = payload.get("patient_id")

    if not isinstance(patient_id, str) or not patient_id.strip():
        raise PermanentRecordError("patient_id must be a non-empty string")

    source = payload.get("source")

    if not isinstance(source, str) or not source.strip():
        raise PermanentRecordError("source must be a non-empty string")

    validate_event_timestamp(payload.get("event_timestamp"))

    present_vitals = 0

    for vital_name in VITAL_RANGES:
        if vital_name not in payload:
            continue

        present_vitals += 1
        validate_numeric_vital(vital_name, payload[vital_name])

    if present_vitals == 0:
        raise PermanentRecordError("at least one supported vital measurement is required")

    replay_attempt = payload.get("_replay_attempt")

    if replay_attempt is not None and (isinstance(replay_attempt, bool) or not isinstance(replay_attempt, int) or replay_attempt < 0):
        raise PermanentRecordError("_replay_attempt must be a non-negative integer")
