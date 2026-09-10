from datetime import UTC, datetime
from math import isfinite
from typing import Any

VITAL_FIELDS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp")


def vital_timestamp_key(field: str) -> str:
    return f"{field}_event_timestamp"


def merge_vitals(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    update_event_timestamp = update.get("event_timestamp")
    legacy_current_timestamp = current.get("event_timestamp")

    if legacy_current_timestamp:
        for field in VITAL_FIELDS:
            if current.get(field) is not None:
                merged.setdefault(vital_timestamp_key(field), legacy_current_timestamp)

    for key, value in update.items():
        if key not in VITAL_FIELDS and not key.endswith("_event_timestamp") and key != "event_timestamp":
            merged[key] = value

    for field in VITAL_FIELDS:
        if field not in update:
            continue

        timestamp_key = vital_timestamp_key(field)
        current_timestamp = parse_event_timestamp(current.get(timestamp_key) or current.get("event_timestamp"))
        update_timestamp_value = update.get(timestamp_key) or update_event_timestamp
        update_timestamp = parse_event_timestamp(update_timestamp_value)

        if current_timestamp and update_timestamp and update_timestamp < current_timestamp:
            continue

        merged[field] = update[field]
        if update_timestamp_value:
            merged[timestamp_key] = update_timestamp_value

    field_timestamps = [
        (parsed, merged.get(vital_timestamp_key(field))) for field in VITAL_FIELDS if (parsed := parse_event_timestamp(merged.get(vital_timestamp_key(field))))
    ]
    if field_timestamps:
        merged["event_timestamp"] = max(field_timestamps, key=lambda entry: entry[0])[1]
    elif update_event_timestamp:
        merged["event_timestamp"] = update_event_timestamp

    return merged


def has_new_event(current: dict[str, Any], update: dict[str, Any]) -> bool:
    return merge_vitals(current, update) != current


def parse_event_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)


def is_stale_event(current: dict[str, Any], update: dict[str, Any]) -> bool:
    updated_fields = [field for field in VITAL_FIELDS if field in update]
    if not updated_fields:
        current_timestamp = parse_event_timestamp(current.get("event_timestamp"))
        update_timestamp = parse_event_timestamp(update.get("event_timestamp"))
        return bool(current_timestamp and update_timestamp and update_timestamp < current_timestamp)

    stale_fields = 0
    for field in updated_fields:
        current_timestamp = parse_event_timestamp(current.get(vital_timestamp_key(field)) or current.get("event_timestamp"))
        update_timestamp = parse_event_timestamp(update.get(vital_timestamp_key(field)) or update.get("event_timestamp"))
        stale_fields += int(bool(current_timestamp and update_timestamp and update_timestamp < current_timestamp))

    return stale_fields == len(updated_fields)


def event_age_seconds(vitals: dict[str, Any], now: datetime | None = None) -> float | None:
    event_timestamps = [
        timestamp
        for field in VITAL_FIELDS
        if vitals.get(field) is not None
        if (timestamp := parse_event_timestamp(vitals.get(vital_timestamp_key(field)) or vitals.get("event_timestamp")))
    ]
    if not event_timestamps:
        legacy_timestamp = parse_event_timestamp(vitals.get("event_timestamp"))
        if not legacy_timestamp:
            return None
        event_timestamps = [legacy_timestamp]
    current_time = now or datetime.now(UTC)
    return min(max((current_time - timestamp).total_seconds(), 0.0) for timestamp in event_timestamps)


def freshness_status(age_seconds: float | None, fresh_threshold_seconds: float, delayed_threshold_seconds: float) -> str:
    if age_seconds is None:
        return "No data"
    if age_seconds <= fresh_threshold_seconds:
        return "Current"
    if age_seconds <= delayed_threshold_seconds:
        return "Delayed"
    return "Stale"


def parse_patient_ids(value: str) -> tuple[str, ...]:
    return tuple(patient_id.strip() for patient_id in value.split(",") if patient_id.strip())


def vital_warning_parameter_score(field: str, value: Any) -> int | None:
    if value is None:
        return None
    try:
        measurement = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(measurement):
        return None
    if field == "heart_rate":
        if measurement <= 40 or measurement >= 131:
            return 3
        if 111 <= measurement <= 130:
            return 2
        if 41 <= measurement <= 50 or 91 <= measurement <= 110:
            return 1
    elif field == "spo2":
        if measurement <= 91:
            return 3
        if measurement <= 93:
            return 2
        if measurement <= 95:
            return 1
    elif field == "respiratory_rate":
        if measurement <= 8 or measurement >= 25:
            return 3
        if 21 <= measurement <= 24:
            return 2
        if 9 <= measurement <= 11:
            return 1
    elif field == "systolic_bp":
        if measurement <= 90 or measurement >= 220:
            return 3
        if measurement <= 100:
            return 2
        if measurement <= 110:
            return 1
    return 0


def patient_priority(vitals: dict[str, Any]) -> tuple[int, str]:
    fields = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp")
    present_fields = [field for field in fields if vitals.get(field) is not None]
    if not present_fields:
        return -1, "No data"

    parameter_scores = [vital_warning_parameter_score(field, vitals.get(field)) for field in present_fields]
    valid_scores = [score for score in parameter_scores if score is not None]
    total_score = sum(valid_scores)

    if total_score >= 7 or any(score == 3 for score in valid_scores):
        return total_score, "Urgent"
    if len(valid_scores) != len(parameter_scores) or total_score:
        return max(total_score, 1), "Review"
    return 0, "Stable"


def measurement_delta(current: dict[str, Any], previous: dict[str, Any] | None, field: str) -> float | None:
    if not previous or current.get(field) is None or previous.get(field) is None:
        return None
    return float(current[field]) - float(previous[field])
