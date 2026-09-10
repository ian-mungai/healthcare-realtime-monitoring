from datetime import UTC, datetime

from dashboard.state import (
    event_age_seconds,
    freshness_status,
    has_new_event,
    is_stale_event,
    measurement_delta,
    merge_vitals,
    parse_event_timestamp,
    parse_patient_ids,
    patient_priority,
    vital_warning_parameter_score,
)


def test_merge_vitals_preserves_measurements_missing_from_partial_update() -> None:
    current = {"patient_id": "1000", "heart_rate": 82.0, "spo2": 97.0}
    update = {"patient_id": "1000", "respiratory_rate": 18.0}

    assert merge_vitals(current, update) == {"patient_id": "1000", "heart_rate": 82.0, "spo2": 97.0, "respiratory_rate": 18.0}


def test_merge_vitals_tracks_freshness_per_measurement() -> None:
    current = {
        "patient_id": "1000",
        "heart_rate": 82.0,
        "heart_rate_event_timestamp": "2026-09-03T16:00:00Z",
        "spo2": 97.0,
        "spo2_event_timestamp": "2026-09-03T15:30:00Z",
    }
    update = {"patient_id": "1000", "event_timestamp": "2026-09-03T16:01:00Z", "heart_rate": 84.0}

    merged = merge_vitals(current, update)

    assert merged["heart_rate_event_timestamp"] == "2026-09-03T16:01:00Z"
    assert merged["spo2_event_timestamp"] == "2026-09-03T15:30:00Z"
    assert event_age_seconds(merged, datetime(2026, 9, 3, 16, 1, tzinfo=UTC)) == 0


def test_merge_vitals_migrates_legacy_shared_timestamp() -> None:
    current = {"event_timestamp": "2026-09-03T15:30:00Z", "heart_rate": 82.0, "spo2": 97.0}
    update = {"event_timestamp": "2026-09-03T16:01:00Z", "heart_rate": 84.0}

    merged = merge_vitals(current, update)

    assert merged["heart_rate_event_timestamp"] == "2026-09-03T16:01:00Z"
    assert merged["spo2_event_timestamp"] == "2026-09-03T15:30:00Z"


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


def test_event_age_uses_latest_measurement_when_vitals_have_different_cadences() -> None:
    now = datetime(2026, 9, 3, 16, 1, tzinfo=UTC)
    vitals = {
        "heart_rate": 82,
        "heart_rate_event_timestamp": "2026-09-03T16:00:55Z",
        "systolic_bp": 119,
        "systolic_bp_event_timestamp": "2026-09-03T15:50:00Z",
    }

    assert event_age_seconds(vitals, now) == 5


def test_parse_event_timestamp_rejects_invalid_values() -> None:
    assert parse_event_timestamp("not-a-timestamp") is None


def test_parse_patient_ids_ignores_empty_values_and_whitespace() -> None:
    assert parse_patient_ids("1000, 1002,,1004 ") == ("1000", "1002", "1004")


def test_vital_warning_parameter_score_uses_adult_warning_boundaries() -> None:
    assert vital_warning_parameter_score("heart_rate", 90) == 0
    assert vital_warning_parameter_score("heart_rate", 131) == 3
    assert vital_warning_parameter_score("spo2", 95) == 1
    assert vital_warning_parameter_score("respiratory_rate", 25) == 3
    assert vital_warning_parameter_score("systolic_bp", 100) == 2


def test_patient_priority_uses_summed_vital_warning_score() -> None:
    assert patient_priority({"heart_rate": 82, "spo2": 98, "respiratory_rate": 18, "systolic_bp": 119}) == (0, "Stable")
    assert patient_priority({"heart_rate": 82, "spo2": 90, "respiratory_rate": 18, "systolic_bp": 119}) == (3, "Urgent")
    assert patient_priority({"heart_rate": 115, "spo2": 93, "respiratory_rate": 23, "systolic_bp": 100}) == (8, "Urgent")
    assert patient_priority({}) == (-1, "No data")


def test_vital_warning_score_handles_malformed_measurements() -> None:
    assert vital_warning_parameter_score("heart_rate", "not-a-number") is None
    assert vital_warning_parameter_score("spo2", float("nan")) is None
    assert patient_priority({"heart_rate": "not-a-number"}) == (1, "Review")


def test_measurement_delta_compares_snapshots() -> None:
    assert measurement_delta({"heart_rate": 88}, {"heart_rate": 82}, "heart_rate") == 6
    assert measurement_delta({"heart_rate": 88}, None, "heart_rate") is None
