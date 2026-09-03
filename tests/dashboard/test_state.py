from dashboard.state import has_new_event, measurement_delta, merge_vitals, news2_parameter_score, parse_patient_ids, patient_priority


def test_merge_vitals_preserves_measurements_missing_from_partial_update() -> None:
    current = {"patient_id": "1000", "heart_rate": 82.0, "spo2": 97.0}
    update = {"patient_id": "1000", "respiratory_rate": 18.0}

    assert merge_vitals(current, update) == {
        "patient_id": "1000",
        "heart_rate": 82.0,
        "spo2": 97.0,
        "respiratory_rate": 18.0,
    }


def test_has_new_event_compares_event_timestamps() -> None:
    current = {"event_timestamp": "2026-09-03T16:00:00Z"}

    assert has_new_event(current, {"event_timestamp": "2026-09-03T16:00:01Z"}) is True
    assert has_new_event(current, {"event_timestamp": "2026-09-03T16:00:00Z"}) is False
    assert has_new_event(current, {}) is False


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
