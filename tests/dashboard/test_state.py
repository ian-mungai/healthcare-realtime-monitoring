from datetime import UTC, datetime

from dashboard.state import (
    analytical_quarantine_fields,
    event_age_seconds,
    freshness_status,
    has_new_event,
    is_stale_event,
    measurement_age_seconds,
    measurement_delta,
    merge_vitals,
    parse_event_timestamp,
    patient_priority,
    vital_warning_parameter_score,
)
from testkit import expect


def test_merge_vitals_preserves_measurements_missing_from_partial_update() -> None:
    current = {"patient_id": "1000", "heart_rate": 82.0, "spo2": 97.0}
    update = {"patient_id": "1000", "respiratory_rate": 18.0}

    expect.equal(merge_vitals(current, update), {"patient_id": "1000", "heart_rate": 82.0, "spo2": 97.0, "respiratory_rate": 18.0})


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

    expect.equal(merged["heart_rate_event_timestamp"], "2026-09-03T16:01:00Z")
    expect.equal(merged["spo2_event_timestamp"], "2026-09-03T15:30:00Z")
    expect.equal(event_age_seconds(merged, datetime(2026, 9, 3, 16, 1, tzinfo=UTC)), 0)


def test_merge_vitals_migrates_legacy_shared_timestamp() -> None:
    current = {"event_timestamp": "2026-09-03T15:30:00Z", "heart_rate": 82.0, "spo2": 97.0}
    update = {"event_timestamp": "2026-09-03T16:01:00Z", "heart_rate": 84.0}

    merged = merge_vitals(current, update)

    expect.equal(merged["heart_rate_event_timestamp"], "2026-09-03T16:01:00Z")
    expect.equal(merged["spo2_event_timestamp"], "2026-09-03T15:30:00Z")


def test_has_new_event_compares_event_timestamps() -> None:
    current = {"event_timestamp": "2026-09-03T16:00:00Z"}

    expect.identical(has_new_event(current, {"event_timestamp": "2026-09-03T16:00:01Z"}), True)
    expect.identical(has_new_event(current, {"event_timestamp": "2026-09-03T16:00:00Z"}), False)
    expect.identical(has_new_event(current, {}), False)


def test_event_ordering_ignores_out_of_order_updates() -> None:
    current = {"event_timestamp": "2026-09-03T16:00:02Z"}

    expect.identical(is_stale_event(current, {"event_timestamp": "2026-09-03T16:00:01Z"}), True)
    expect.identical(is_stale_event(current, {"event_timestamp": "2026-09-03T16:00:02Z"}), False)
    expect.identical(is_stale_event(current, {"event_timestamp": "2026-09-03T16:00:03Z"}), False)


def test_event_age_and_freshness_status_reflect_each_patient_feed() -> None:
    now = datetime(2026, 9, 3, 16, 1, tzinfo=UTC)
    vitals = {"event_timestamp": "2026-09-03T16:00:30Z"}

    expect.equal(event_age_seconds(vitals, now), 30)
    expect.equal(freshness_status(10, fresh_threshold_seconds=15, delayed_threshold_seconds=60), "Current")
    expect.equal(freshness_status(30, fresh_threshold_seconds=15, delayed_threshold_seconds=60), "Delayed")
    expect.equal(freshness_status(61, fresh_threshold_seconds=15, delayed_threshold_seconds=60), "Stale")
    expect.equal(freshness_status(None, fresh_threshold_seconds=15, delayed_threshold_seconds=60), "No data")


def test_event_age_uses_latest_measurement_when_vitals_have_different_cadences() -> None:
    now = datetime(2026, 9, 3, 16, 1, tzinfo=UTC)
    vitals = {"heart_rate": 82, "heart_rate_event_timestamp": "2026-09-03T16:00:55Z", "systolic_bp": 119, "systolic_bp_event_timestamp": "2026-09-03T15:50:00Z"}

    expect.equal(event_age_seconds(vitals, now), 5)
    expect.equal(measurement_age_seconds(vitals, "heart_rate", now), 5)
    expect.equal(measurement_age_seconds(vitals, "systolic_bp", now), 660)


def test_parse_event_timestamp_rejects_invalid_values() -> None:
    expect.identical(parse_event_timestamp("not-a-timestamp"), None)


def test_vital_warning_parameter_score_uses_adult_warning_boundaries() -> None:
    expect.equal(vital_warning_parameter_score("heart_rate", 90), 0)
    expect.equal(vital_warning_parameter_score("heart_rate", 131), 3)
    expect.equal(vital_warning_parameter_score("spo2", 95), 1)
    expect.equal(vital_warning_parameter_score("respiratory_rate", 25), 3)
    expect.equal(vital_warning_parameter_score("systolic_bp", 100), 2)


def test_patient_priority_uses_summed_vital_warning_score() -> None:
    expect.equal(patient_priority({"heart_rate": 82, "spo2": 98, "respiratory_rate": 18, "systolic_bp": 119}), (0, "Stable"))
    expect.equal(patient_priority({"heart_rate": 82, "spo2": 90, "respiratory_rate": 18, "systolic_bp": 119}), (3, "Urgent"))
    expect.equal(patient_priority({"heart_rate": 115, "spo2": 93, "respiratory_rate": 23, "systolic_bp": 100}), (8, "Urgent"))
    expect.equal(patient_priority({}), (-1, "No data"))


def test_vital_warning_score_handles_malformed_measurements() -> None:
    expect.identical(vital_warning_parameter_score("heart_rate", "not-a-number"), None)
    expect.identical(vital_warning_parameter_score("spo2", float("nan")), None)
    expect.equal(patient_priority({"heart_rate": "not-a-number"}), (1, "Review"))


def test_measurement_delta_compares_snapshots() -> None:
    expect.equal(measurement_delta({"heart_rate": 88}, {"heart_rate": 82}, "heart_rate"), 6)
    expect.identical(measurement_delta({"heart_rate": 88}, None, "heart_rate"), None)


def test_analytical_quarantine_fields_use_catalog_ranges() -> None:
    expect.equal(analytical_quarantine_fields({"systolic_bp": 261, "diastolic_bp": 29, "heart_rate": 82}), ("systolic_bp", "diastolic_bp"))
    expect.equal(analytical_quarantine_fields({"systolic_bp": 260, "diastolic_bp": 30}), ())


def test_measurement_delta_rejects_malformed_or_non_finite_values() -> None:
    expect.identical(measurement_delta({"heart_rate": "invalid"}, {"heart_rate": 82}, "heart_rate"), None)
    expect.identical(measurement_delta({"heart_rate": float("nan")}, {"heart_rate": 82}, "heart_rate"), None)


def test_merge_vitals_keeps_bedside_measures_with_their_own_freshness() -> None:
    current = {"patient_id": "1000", "heart_rate": 82.0, "heart_rate_event_timestamp": "2026-08-31T22:40:00Z"}
    update = {"patient_id": "1000", "event_timestamp": "2026-08-31T22:45:00Z", "temperature": 38.4, "consciousness_level": 1}

    merged = merge_vitals(current, update)

    expect.equal((merged["temperature"], merged["consciousness_level"]), (38.4, 1))
    expect.equal(merged["temperature_event_timestamp"], "2026-08-31T22:45:00Z")
    expect.equal(merged["heart_rate_event_timestamp"], "2026-08-31T22:40:00Z")
