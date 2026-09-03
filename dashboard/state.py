from typing import Any


def merge_vitals(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    return {**current, **update}


def has_new_event(current: dict[str, Any], update: dict[str, Any]) -> bool:
    return bool(update.get("event_timestamp") and update.get("event_timestamp") != current.get("event_timestamp"))


def parse_patient_ids(value: str) -> tuple[str, ...]:
    return tuple(patient_id.strip() for patient_id in value.split(",") if patient_id.strip())


def news2_parameter_score(field: str, value: Any) -> int:
    if value is None:
        return 0
    measurement = float(value)
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
    if not any(vitals.get(field) is not None for field in ("heart_rate", "spo2", "respiratory_rate", "systolic_bp")):
        return -1, "No data"
    score = max(
        news2_parameter_score("heart_rate", vitals.get("heart_rate")),
        news2_parameter_score("spo2", vitals.get("spo2")),
        news2_parameter_score("respiratory_rate", vitals.get("respiratory_rate")),
        news2_parameter_score("systolic_bp", vitals.get("systolic_bp")),
    )
    if score == 3:
        return score, "Urgent"
    if score:
        return score, "Review"
    return score, "Stable"


def measurement_delta(current: dict[str, Any], previous: dict[str, Any] | None, field: str) -> float | None:
    if not previous or current.get(field) is None or previous.get(field) is None:
        return None
    return float(current[field]) - float(previous[field])
