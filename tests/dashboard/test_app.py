from __future__ import annotations

import os
import queue
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

os.environ["VITALS_API_ENDPOINT"] = "https://api.example.com/development"
os.environ["VITALS_WEBSOCKET_URL"] = "wss://websocket.example.com/development"
os.environ["FHIR_RESOURCE_MAP_FILE"] = str(Path(__file__).resolve().parents[1] / "fixtures" / "dashboard_fhir_resource_map.json")

from dashboard import app
from testkit import expect


class SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def test_api_and_websocket_urls_use_patient_id(monkeypatch) -> None:
    response = Mock(status_code=200)
    response.json.return_value = {"patient_id": "1000", "heart_rate": 82}
    monkeypatch.setattr(app, "get_sigv4_headers", lambda url: {"Authorization": "signed"})
    request = Mock(return_value=response)
    monkeypatch.setattr(app.requests, "get", request)

    expect.equal(app.get_initial_vitals("1000"), {"patient_id": "1000", "heart_rate": 82})
    request.assert_called_once_with("https://api.example.com/development/patients/1000/vitals", headers={"Authorization": "signed"}, timeout=10)
    if not app.websocket_subscription_url("1000").endswith("?patient_id=1000"):
        expect.fail('expected: app.websocket_subscription_url("1000").endswith("?patient_id=1000")')


def test_api_returns_none_for_patient_without_vitals(monkeypatch) -> None:
    monkeypatch.setattr(app, "get_sigv4_headers", lambda url: {})
    monkeypatch.setattr(app.requests, "get", Mock(return_value=Mock(status_code=404)))

    expect.identical(app.get_initial_vitals("1000"), None)


def test_append_history_merges_same_timestamp_and_keeps_new_snapshot(monkeypatch) -> None:
    state = SessionState(cohort_history={"1000": deque(maxlen=app.HISTORY_SIZE)})
    monkeypatch.setattr(app.st, "session_state", state)

    app.append_history("1000", {"event_timestamp": "2026-09-09T12:00:00Z", "heart_rate": 82})
    app.append_history("1000", {"event_timestamp": "2026-09-09T12:00:00Z", "spo2": 98})
    app.append_history("1000", {"event_timestamp": "2026-09-09T12:00:01Z", "heart_rate": 83})

    expect.equal(len(state.cohort_history["1000"]), 2)
    expect.equal(state.cohort_history["1000"][0]["spo2"], 98)
    expect.equal(state.cohort_history["1000"][1]["heart_rate"], 83)


def test_websocket_messages_keep_latest_patient_update(monkeypatch) -> None:
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    messages.put({"patient_id": "1000", "event_timestamp": "2026-09-09T12:00:00Z", "heart_rate": 80})
    messages.put({"patient_id": "1000", "event_timestamp": "2026-09-09T12:00:01Z", "heart_rate": 81, "_received_at": "2026-09-09T12:00:01.250000+00:00"})
    messages.put({"patient_id": "unknown", "heart_rate": 200})
    # Load-test events reach cohort subscribers too; the dashboard must not show them as patient vitals.
    messages.put({"patient_id": "1000", "event_timestamp": "2026-09-09T12:00:02Z", "heart_rate": 150, "source": "load_test"})
    state = SessionState(
        message_queue=messages,
        cohort_vitals={},
        cohort_history={patient_id: deque(maxlen=app.HISTORY_SIZE) for patient_id in app.PATIENT_IDS},
        websocket_latency_ms={},
    )
    monkeypatch.setattr(app.st, "session_state", state)

    app.process_websocket_messages()

    expect.equal(state.cohort_vitals["1000"]["heart_rate"], 81)
    expect.equal(len(state.cohort_history["1000"]), 1)
    expect.equal(state.websocket_latency_ms["1000"], 250)


def test_dashboard_formatting_and_clinical_status_helpers() -> None:
    expect.equal(len(app.PATIENT_IDS), 10)
    expect.equal(app.format_value(None), "--")
    expect.equal(app.format_value(82.25, decimals=1), "82.2")
    expect.equal(app.format_delta(-2, "bpm"), "-2 bpm")
    expect.equal(app.heart_rate_status(59), "Low")
    expect.equal(app.heart_rate_status(82), "Normal")
    expect.equal(app.heart_rate_status(101), "High")
    expect.equal(app.spo2_status(89), "Critical")
    expect.equal(app.spo2_status(94), "Low")
    expect.equal(app.spo2_status(98), "Normal")
    expect.equal(app.respiratory_rate_status(11), "Low")
    expect.equal(app.respiratory_rate_status(18), "Normal")
    expect.equal(app.respiratory_rate_status(21), "High")
    expect.equal(app.patient_freshness(10), ("Current", "green"))
    expect.equal(app.patient_freshness(10.01), ("Delayed", "orange"))
    expect.equal(app.patient_freshness(90), ("Stale", "red"))
    expect.equal(app.format_event_time("invalid"), "invalid")


def test_live_vitals_applies_measurement_specific_freshness() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    vitals = {
        "patient_id": "1000",
        "event_timestamp": "2026-09-11T11:59:55Z",
        "heart_rate": 82,
        "heart_rate_event_timestamp": "2026-09-11T11:59:55Z",
        "spo2": 98,
        "spo2_event_timestamp": "2026-09-11T11:59:49Z",
        "systolic_bp": 119,
        "systolic_bp_event_timestamp": "2026-09-11T11:55:00Z",
        "diastolic_bp": 73,
        "diastolic_bp_event_timestamp": "2026-09-11T11:54:49Z",
    }

    filtered = app.live_vitals(vitals, now)

    expect.equal(filtered["heart_rate"], 82)
    expect.equal(filtered["systolic_bp"], 119)
    expect.not_in("spo2", filtered)
    expect.not_in("diastolic_bp", filtered)


def test_warning_vitals_require_contemporaneous_blood_pressure() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    vitals = {
        "patient_id": "1000",
        "heart_rate": 82,
        "heart_rate_event_timestamp": "2026-09-11T11:59:55Z",
        "systolic_bp": 90,
        "systolic_bp_event_timestamp": "2026-09-11T11:55:00Z",
    }

    expect.equal(app.warning_vitals(vitals, now), {"patient_id": "1000", "heart_rate": 82, "heart_rate_event_timestamp": "2026-09-11T11:59:55Z"})


def test_analytical_quarantine_label_identifies_out_of_range_vitals() -> None:
    expect.equal(app.analytical_quarantine_label({"systolic_bp": 261, "diastolic_bp": 29}), "Systolic BP, Diastolic BP")
    expect.identical(app.analytical_quarantine_label({"systolic_bp": 260, "diastolic_bp": 30}), None)


def test_history_dataframe_includes_required_columns(monkeypatch) -> None:
    state = SessionState(cohort_history={"1000": [{"timestamp": datetime(2026, 9, 9, 12, tzinfo=UTC), "patient_id": "1000", "heart_rate": 82}]})
    monkeypatch.setattr(app.st, "session_state", state)

    dataframe = app.history_dataframe()

    expect.equal(list(dataframe["patient_id"]), ["1000"])
    if not ({"heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp"} <= set(dataframe.columns)):
        expect.fail('expected: {"heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp"} <= set(dataframe.columns)')


def test_bedside_measure_status_helpers() -> None:
    expect.equal(app.temperature_status(None), "Unknown")
    expect.equal(app.temperature_status(35.0), "Low")
    expect.equal(app.temperature_status(37.1), "Normal")
    expect.equal(app.temperature_status(38.6), "Fever")
    expect.equal(app.oxygen_status(21.0), "Room air")
    expect.equal(app.oxygen_status(28.0), "Supplemental")
    expect.equal(app.acvpu_label(0), "A · Alert")
    expect.equal(app.acvpu_label(1), "C · Confused")
    expect.equal(app.acvpu_label(None), "--")


def test_bedside_measures_stay_live_for_the_observation_set_interval() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    vitals = {
        "patient_id": "1000",
        "temperature": 37.1,
        "temperature_event_timestamp": "2026-09-11T11:56:00Z",
        "consciousness_level": 0,
        "consciousness_level_event_timestamp": "2026-09-11T11:50:00Z",
    }

    filtered = app.live_vitals(vitals, now)

    expect.equal(filtered["temperature"], 37.1)
    expect.not_in("consciousness_level", filtered)


# Live NEWS2 and the real-time model score on the watchlist. Failure modes: NEWS2 counts a stale bedside measure as
# current; NEWS2 here disagrees with the endpoint's (services/early_warning/scoring.py); a patient without an
# early-warning result breaks the refresh; a score is shown without its model version or before the window closes.
LIVE = {
    "respiratory_rate": 22,
    "respiratory_rate_event_timestamp": "2026-09-11T11:59:58Z",
    "spo2": 93,
    "spo2_event_timestamp": "2026-09-11T11:59:58Z",
    "heart_rate": 95,
    "heart_rate_event_timestamp": "2026-09-11T11:59:58Z",
    "systolic_bp": 120,
    "systolic_bp_event_timestamp": "2026-09-11T11:58:00Z",
    "inhaled_oxygen_concentration": 21,
    "inhaled_oxygen_concentration_event_timestamp": "2026-09-11T11:58:00Z",
    "consciousness_level": 0,
    "consciousness_level_event_timestamp": "2026-09-11T11:58:00Z",
    "temperature": 37.0,
    "temperature_event_timestamp": "2026-09-11T11:58:00Z",
}


def test_live_news2_uses_only_current_measurements() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)

    expect.equal((app.live_news2(LIVE, now)["total"], app.live_news2(LIVE, now)["band"]), (5, "medium"))
    stale = {**LIVE, "temperature_event_timestamp": "2026-09-11T11:50:00Z"}
    expect.equal(app.live_news2(stale, now)["missing"], ["temperature"])
    expect.equal(app.news2_label(app.live_news2(stale, now)), "NEWS2 -- · missing Temperature")
    expect.equal(app.news2_label(app.live_news2(LIVE, now)), "NEWS2 **5** · :orange[Medium]")


def test_early_warning_requests_are_signed_and_a_missing_patient_is_none(monkeypatch) -> None:
    monkeypatch.setattr(app, "get_sigv4_headers", lambda url: {"Authorization": "signed"})
    request = Mock(return_value=Mock(status_code=404))
    monkeypatch.setattr(app.requests, "get", request)

    expect.identical(app.get_early_warning("1000"), None)
    request.assert_called_once_with("https://api.example.com/development/patients/1000/early-warning", headers={"Authorization": "signed"}, timeout=10)


def test_model_labels_name_the_state_and_the_version() -> None:
    expect.equal(app.model_label(None), "Model score unavailable")
    expect.equal(app.model_label({"status": "window_open", "window_closes_at": "2026-09-11T12:15:00Z"}), "Model scores at 12:15:00 UTC")
    expect.equal(app.model_label({"status": "scored", "probability": 0.4213, "model_version": "logistic-abc"}), "Model risk **42%** · logistic-abc")
    expect.equal(app.model_label({"status": "no_approved_model"}), "Model: no approved model")
