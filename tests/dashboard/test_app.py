from __future__ import annotations

import os
import queue
from collections import deque
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

os.environ.setdefault("VITALS_API_ENDPOINT", "https://api.example.com/development")
os.environ.setdefault("VITALS_WEBSOCKET_URL", "wss://websocket.example.com/development")

from dashboard import app


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

    assert app.get_initial_vitals("1000") == {"patient_id": "1000", "heart_rate": 82}
    request.assert_called_once_with("https://api.example.com/development/patients/1000/vitals", headers={"Authorization": "signed"}, timeout=10)
    assert app.websocket_subscription_url("1000").endswith("?patient_id=1000")


def test_api_returns_none_for_patient_without_vitals(monkeypatch) -> None:
    monkeypatch.setattr(app, "get_sigv4_headers", lambda url: {})
    monkeypatch.setattr(app.requests, "get", Mock(return_value=Mock(status_code=404)))

    assert app.get_initial_vitals("1000") is None


def test_append_history_merges_same_timestamp_and_keeps_new_snapshot(monkeypatch) -> None:
    state = SessionState(cohort_history={"1000": deque(maxlen=app.HISTORY_SIZE)})
    monkeypatch.setattr(app.st, "session_state", state)

    app.append_history("1000", {"event_timestamp": "2026-09-09T12:00:00Z", "heart_rate": 82})
    app.append_history("1000", {"event_timestamp": "2026-09-09T12:00:00Z", "spo2": 98})
    app.append_history("1000", {"event_timestamp": "2026-09-09T12:00:01Z", "heart_rate": 83})

    assert len(state.cohort_history["1000"]) == 2
    assert state.cohort_history["1000"][0]["spo2"] == 98
    assert state.cohort_history["1000"][1]["heart_rate"] == 83


def test_websocket_messages_keep_latest_patient_update(monkeypatch) -> None:
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    messages.put({"patient_id": "1000", "event_timestamp": "2026-09-09T12:00:00Z", "heart_rate": 80})
    messages.put({"patient_id": "1000", "event_timestamp": "2026-09-09T12:00:01Z", "heart_rate": 81, "_received_at": "2026-09-09T12:00:01.250000+00:00"})
    messages.put({"patient_id": "unknown", "heart_rate": 200})
    state = SessionState(
        message_queue=messages,
        cohort_vitals={},
        cohort_history={patient_id: deque(maxlen=app.HISTORY_SIZE) for patient_id in app.PATIENT_IDS},
        websocket_latency_ms={},
    )
    monkeypatch.setattr(app.st, "session_state", state)

    app.process_websocket_messages()

    assert state.cohort_vitals["1000"]["heart_rate"] == 81
    assert len(state.cohort_history["1000"]) == 1
    assert state.websocket_latency_ms["1000"] == 250


def test_dashboard_formatting_and_clinical_status_helpers() -> None:
    assert len(app.PATIENT_IDS) == 10
    assert app.format_value(None) == "--"
    assert app.format_value(82.25, decimals=1) == "82.2"
    assert app.format_delta(-2, "bpm") == "-2 bpm"
    assert app.heart_rate_status(59) == "Low"
    assert app.heart_rate_status(82) == "Normal"
    assert app.heart_rate_status(101) == "High"
    assert app.spo2_status(89) == "Critical"
    assert app.spo2_status(94) == "Low"
    assert app.spo2_status(98) == "Normal"
    assert app.respiratory_rate_status(11) == "Low"
    assert app.respiratory_rate_status(18) == "Normal"
    assert app.respiratory_rate_status(21) == "High"
    assert app.patient_freshness(10) == ("Current", "green")
    assert app.patient_freshness(90) == ("Stale", "red")
    assert app.format_event_time("invalid") == "invalid"


def test_history_dataframe_includes_required_columns(monkeypatch) -> None:
    state = SessionState(cohort_history={"1000": [{"timestamp": datetime(2026, 9, 9, 12, tzinfo=UTC), "patient_id": "1000", "heart_rate": 82}]})
    monkeypatch.setattr(app.st, "session_state", state)

    dataframe = app.history_dataframe()

    assert list(dataframe["patient_id"]) == ["1000"]
    assert {"heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp"} <= set(dataframe.columns)
