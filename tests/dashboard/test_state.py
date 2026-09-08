from datetime import UTC, datetime

from dashboard.state import (
    event_age_seconds,
    freshness_status,
    has_new_event,
    is_stale_event,
    measurement_delta,
    merge_vitals,
    news2_parameter_score,
    parse_event_timestamp,
    parse_patient_ids,
    patient_priority,
)


def test_merge_vitals_preserves_measurements_missing_from_partial_update() -> None:
    current = {"patient_id": "1000", "heart_rate": 82.0, "spo2": 97.0}
    update = {"patient_id": "1000", "respiratory_rate": 18.0}

    assert merge_vitals(current, update) == {"patient_id": "1000", "heart_rate": 82.0, "spo2": 97.0, "respiratory_rate": 18.0}


def test_has_new_event_compares_event_timestamps() -> None:
    current = {"event_timestamp": "2026-09-03T16:00:00Z"}

    assert has_new_event(current, {"event_timestamp": "2026-09-03T16:00:01Z"}) is True
    assert has_new_event(current, {"event_timestamp": "2026-09-03T16:00:00Z"}) is False
    assert has_new_event(current, {}) is False


def test_event_ordering_ignores_out_of_order_updates() -> None:
    current = {"event_timestamp": "2026-09-03T16:00:02Z"}

    assert is_stale_event(current, {"event_timestamp": "2026-09-03T16:00:01Z"}) is True
    assert is_stale_event(current, {"event_timestamp": "2026-09-03T16:00:02Z"}) is False
    assert is_stale_event(current, {"event_timestamp": "2026-09-03T16:00:03Z"}) is False


def test_event_age_and_freshness_status_reflect_each_patient_feed() -> None:
    now = datetime(2026, 9, 3, 16, 1, tzinfo=UTC)
    vitals = {"event_timestamp": "2026-09-03T16:00:30Z"}

    assert event_age_seconds(vitals, now) == 30
    assert freshness_status(10, fresh_threshold_seconds=15, delayed_threshold_seconds=60) == "Current"
    assert freshness_status(30, fresh_threshold_seconds=15, delayed_threshold_seconds=60) == "Delayed"
    assert freshness_status(61, fresh_threshold_seconds=15, delayed_threshold_seconds=60) == "Stale"
    assert freshness_status(None, fresh_threshold_seconds=15, delayed_threshold_seconds=60) == "No data"


def test_parse_event_timestamp_rejects_invalid_values() -> None:
    assert parse_event_timestamp("not-a-timestamp") is None


def test_parse_patient_ids_ignores_empty_values_and_whitespace() -> None:
    assert parse_patient_ids("1000, 1002,,1004 ") == ("1000", "1002", "1004")


def test_news2_parameter_score_uses_adult_scale_one_boundaries() -> None:
    assert news2_parameter_score("heart_rate", 90) == 0
    assert news2_parameter_score("heart_rate", 131) == 3
    assert news2_parameter_score("spo2", 95) == 1
    assert news2_parameter_score("respiratory_rate", 25) == 3
    assert news2_parameter_score("systolic_bp", 100) == 2


def test_patient_priority_uses_highest_individual_parameter_score() -> None:
    assert patient_priority({"heart_rate": 82, "spo2": 98, "respiratory_rate": 18, "systolic_bp": 119}) == (0, "Stable")
    assert patient_priority({"heart_rate": 82, "spo2": 90, "respiratory_rate": 18, "systolic_bp": 119}) == (3, "Urgent")
    assert patient_priority({}) == (-1, "No data")


def test_measurement_delta_compares_snapshots() -> None:
    assert measurement_delta({"heart_rate": 88}, {"heart_rate": 82}, "heart_rate") == 6
    assert measurement_delta({"heart_rate": 88}, None, "heart_rate") is None
