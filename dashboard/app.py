import json
import os
import queue
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import requests
import streamlit as st
import websocket

from dashboard.aws_auth import get_sigv4_headers
from dashboard.state import (
    event_age_seconds,
    freshness_status,
    has_new_event,
    is_stale_event,
    measurement_delta,
    merge_vitals,
    parse_patient_ids,
    patient_priority,
)

PATIENT_IDS = parse_patient_ids(os.getenv("PATIENT_IDS", "1000,1002,1004,1006,1008,1010,1012,1014,1016,1018"))
API_ENDPOINT = os.environ["VITALS_API_ENDPOINT"].rstrip("/")
WEBSOCKET_URL = os.environ["VITALS_WEBSOCKET_URL"]

REFRESH_INTERVAL_SECONDS = 0.5
API_REFRESH_INTERVAL_SECONDS = 2.0
HISTORY_SIZE = 60
FRESH_EVENT_AGE_SECONDS = 15.0
DELAYED_EVENT_AGE_SECONDS = 60.0


def get_initial_vitals(patient_id: str) -> dict[str, Any] | None:
    url = f"{API_ENDPOINT}/patients/{patient_id}/vitals"
    response = requests.get(url, headers=get_sigv4_headers(url), timeout=10)

    if response.status_code == 404:
        return None

    response.raise_for_status()

    return response.json()


def get_cohort_vitals() -> dict[str, dict[str, Any]]:
    cohort: dict[str, dict[str, Any]] = {}
    if not PATIENT_IDS:
        return cohort
    with ThreadPoolExecutor(max_workers=min(len(PATIENT_IDS), 10)) as executor:
        futures = {executor.submit(get_initial_vitals, patient_id): patient_id for patient_id in PATIENT_IDS}
        for future in as_completed(futures):
            patient_id = futures[future]
            try:
                vitals = future.result()
                if vitals:
                    cohort[patient_id] = vitals
            except requests.RequestException:
                continue
    return cohort


def websocket_subscription_url(patient_id: str) -> str:
    return f"{WEBSOCKET_URL}?{urlencode({'patient_id': patient_id})}"


def websocket_worker(
    patient_id: str, message_queue: queue.Queue[dict[str, Any]], connection_state: dict[str, dict[str, Any]], connection_state_lock: threading.Lock
) -> None:
    subscription_url = websocket_subscription_url(patient_id)

    def update_connection_state(connected: bool, error: str | None = None) -> None:
        with connection_state_lock:
            connection_state[patient_id] = {"connected": connected, "error": error}

    def on_open(_ws: websocket.WebSocketApp) -> None:
        update_connection_state(connected=True)

    def on_message(_ws: websocket.WebSocketApp, message: str) -> None:
        try:
            payload = json.loads(message)

            if payload.get("patient_id") != patient_id:
                return

            payload["_received_at"] = datetime.now(UTC).isoformat()
            message_queue.put(payload)

        except json.JSONDecodeError as error:
            update_connection_state(connected=False, error=f"Invalid WebSocket message: {error}")

    def on_error(_ws: websocket.WebSocketApp, error: Any) -> None:
        update_connection_state(connected=False, error=str(error))

    def on_close(_ws: websocket.WebSocketApp, _close_status_code: int | None, _close_message: str | None) -> None:
        with connection_state_lock:
            previous_error = connection_state.get(patient_id, {}).get("error")
        update_connection_state(connected=False, error=previous_error)

    while True:
        try:
            signed_headers = get_sigv4_headers(subscription_url)

            ws = websocket.WebSocketApp(
                subscription_url,
                header=[f"{key}: {value}" for key, value in signed_headers.items()],
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            ws.run_forever()

        except Exception as error:
            update_connection_state(connected=False, error=str(error))

        time.sleep(3)


def start_websocket_workers() -> None:
    if "message_queue" not in st.session_state:
        st.session_state.message_queue = queue.Queue()

    if "connection_state" not in st.session_state:
        st.session_state.connection_state = {patient_id: {"connected": False, "error": None} for patient_id in PATIENT_IDS}

    if "connection_state_lock" not in st.session_state:
        st.session_state.connection_state_lock = threading.Lock()

    if "websocket_threads" in st.session_state:
        return

    websocket_threads = {}
    for patient_id in PATIENT_IDS:
        websocket_thread = threading.Thread(
            target=websocket_worker,
            args=(patient_id, st.session_state.message_queue, st.session_state.connection_state, st.session_state.connection_state_lock),
            daemon=True,
            name=f"vitals-websocket-{patient_id}",
        )
        websocket_thread.start()
        websocket_threads[patient_id] = websocket_thread
    st.session_state.websocket_threads = websocket_threads


def append_history(patient_id: str, vitals: dict[str, Any]) -> None:
    event_timestamp = vitals.get("event_timestamp")

    if event_timestamp:
        try:
            timestamp = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

        except ValueError:
            timestamp = datetime.now(UTC)

    else:
        timestamp = datetime.now(UTC)

    snapshot = {
        "timestamp": timestamp,
        "patient_id": patient_id,
        "heart_rate": vitals.get("heart_rate"),
        "spo2": vitals.get("spo2"),
        "respiratory_rate": vitals.get("respiratory_rate"),
        "systolic_bp": vitals.get("systolic_bp"),
        "diastolic_bp": vitals.get("diastolic_bp"),
    }
    history = st.session_state.cohort_history[patient_id]
    if history and history[-1]["timestamp"] == timestamp:
        history[-1] = {**history[-1], **snapshot}
    else:
        history.append(snapshot)


def load_initial_state() -> None:
    if "cohort_vitals" not in st.session_state:
        st.session_state.cohort_vitals = {}

    if "cohort_history" not in st.session_state:
        st.session_state.cohort_history = {patient_id: deque(maxlen=HISTORY_SIZE) for patient_id in PATIENT_IDS}

    if "websocket_latency_ms" not in st.session_state:
        st.session_state.websocket_latency_ms = {}

    if "initial_state_loaded" in st.session_state:
        return

    try:
        cohort_vitals = get_cohort_vitals()
        st.session_state.cohort_vitals.update(cohort_vitals)
        for patient_id, patient_vitals in cohort_vitals.items():
            append_history(patient_id, patient_vitals)

    except Exception as error:
        st.session_state.initial_load_error = str(error)

    st.session_state.initial_state_loaded = True
    st.session_state.last_api_refresh_monotonic = time.monotonic()


def refresh_vitals_from_api() -> None:
    last_refresh = st.session_state.get("last_api_refresh_monotonic", 0.0)
    if time.monotonic() - last_refresh < API_REFRESH_INTERVAL_SECONDS:
        return

    st.session_state.last_api_refresh_monotonic = time.monotonic()

    try:
        cohort_vitals = get_cohort_vitals()
        for patient_id, patient_vitals in cohort_vitals.items():
            current = st.session_state.cohort_vitals.get(patient_id, {})
            if is_stale_event(current, patient_vitals):
                continue
            st.session_state.cohort_vitals[patient_id] = merge_vitals(current, patient_vitals)
            if has_new_event(current, patient_vitals):
                append_history(patient_id, st.session_state.cohort_vitals[patient_id])

        st.session_state.pop("api_refresh_error", None)
    except Exception as error:
        st.session_state.api_refresh_error = str(error)


def process_websocket_messages() -> None:
    latest_payloads: dict[str, dict[str, Any]] = {}

    while True:
        try:
            payload = st.session_state.message_queue.get_nowait()
            patient_id = payload.get("patient_id")
            if patient_id not in PATIENT_IDS:
                continue
            current_payload = latest_payloads.get(patient_id, {})
            if not is_stale_event(current_payload, payload):
                latest_payloads[patient_id] = payload

        except queue.Empty:
            break

    for patient_id, payload in latest_payloads.items():
        received_at = payload.pop("_received_at", None)
        current = st.session_state.cohort_vitals.get(patient_id, {})
        if is_stale_event(current, payload):
            continue
        merged_vitals = merge_vitals(current, payload)
        st.session_state.cohort_vitals[patient_id] = merged_vitals
        if has_new_event(current, payload):
            append_history(patient_id, merged_vitals)

        if received_at and payload.get("event_timestamp"):
            received_time = datetime.fromisoformat(received_at)
            event_time = datetime.fromisoformat(payload["event_timestamp"].replace("Z", "+00:00"))
            st.session_state.websocket_latency_ms[patient_id] = max((received_time - event_time).total_seconds() * 1000, 0.0)


def format_value(value: Any, decimals: int = 0) -> str:
    if value is None:
        return "--"

    try:
        return f"{float(value):.{decimals}f}"

    except (TypeError, ValueError):
        return str(value)


def heart_rate_status(value: Any) -> str:
    if value is None:
        return "Unknown"

    heart_rate = float(value)

    if heart_rate < 60:
        return "Low"

    if heart_rate > 100:
        return "High"

    return "Normal"


def spo2_status(value: Any) -> str:
    if value is None:
        return "Unknown"

    spo2 = float(value)

    if spo2 < 90:
        return "Critical"

    if spo2 < 95:
        return "Low"

    return "Normal"


def respiratory_rate_status(value: Any) -> str:
    if value is None:
        return "Unknown"

    respiratory_rate = float(value)

    if respiratory_rate < 12:
        return "Low"

    if respiratory_rate > 20:
        return "High"

    return "Normal"


def history_dataframe() -> pd.DataFrame:
    rows = [snapshot for history in st.session_state.cohort_history.values() for snapshot in history]
    if not rows:
        return pd.DataFrame()

    dataframe = pd.DataFrame(rows)

    expected_columns = ["timestamp", "patient_id", "heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp"]

    for column in expected_columns:
        if column not in dataframe.columns:
            dataframe[column] = None

    dataframe["timestamp"] = pd.to_datetime(dataframe["timestamp"], utc=True)

    return dataframe


def render_vital_chart(
    dataframe: pd.DataFrame,
    field: str,
    label: str,
    y_title: str,
    y_domain: tuple[float, float],
    reference_values: tuple[float, ...],
    selected_patient: str | None,
) -> None:
    chart_data = dataframe[["timestamp", "patient_id", field]].rename(columns={field: "Value"}).dropna(subset=["Value"])

    if chart_data.empty:
        st.info(f"Waiting for {y_title.lower()} data.")
        return

    base_line = (
        alt.Chart(chart_data)
        .encode(
            x=alt.X("timestamp:T", axis=alt.Axis(title="Time (HH:MM:SS)", format="%H:%M:%S", labelAngle=0, tickCount=6)),
            y=alt.Y("Value:Q", title=y_title, scale=alt.Scale(domain=list(y_domain), zero=False)),
            color=alt.Color(
                "patient_id:N",
                title="Patient",
                scale=alt.Scale(domain=list(PATIENT_IDS), scheme="tableau10"),
                legend=alt.Legend(orient="bottom", direction="horizontal", columns=5, symbolType="stroke"),
            ),
            tooltip=[
                alt.Tooltip("timestamp:T", title="Time", format="%Y-%m-%d %H:%M:%S"),
                alt.Tooltip("patient_id:N", title="Patient"),
                alt.Tooltip("Value:Q", title=label, format=".1f"),
            ],
        )
        .properties(height=300)
    )
    if selected_patient:
        context_lines = base_line.transform_filter(alt.datum.patient_id != selected_patient).mark_line(strokeWidth=1.5, opacity=0.25)
        selected_line = base_line.transform_filter(alt.datum.patient_id == selected_patient).mark_line(strokeWidth=3.5, point=alt.OverlayMarkDef(size=42))
        patient_lines = context_lines + selected_line
    else:
        patient_lines = base_line.mark_line(strokeWidth=2, opacity=0.85)

    reference_data = pd.DataFrame({"Reference": reference_values})
    reference_lines = (
        alt.Chart(reference_data)
        .mark_rule(color="#6b7280", strokeDash=[4, 4], opacity=0.45)
        .encode(
            y=alt.Y("Reference:Q", scale=alt.Scale(domain=list(y_domain), zero=False)), tooltip=[alt.Tooltip("Reference:Q", title="Vital warning boundary")]
        )
    )

    st.altair_chart(reference_lines + patient_lines, width="stretch")


def format_event_time(value: Any) -> str:
    if not value:
        return "--"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def render_trend_charts(selected_patient: str | None) -> None:
    dataframe = history_dataframe()

    st.subheader("Cohort Trends")
    if selected_patient:
        st.caption(f"Patient {selected_patient} is highlighted. All other patients remain visible for comparison.")

    if dataframe.empty:
        st.info("Waiting for live vital events.")
        return

    heart_rate_column, spo2_column = st.columns(2)

    with heart_rate_column:
        st.markdown("#### Heart Rate")
        render_vital_chart(dataframe, "heart_rate", "Heart Rate", "bpm", (30, 150), (40, 50, 90, 110, 130), selected_patient)

    with spo2_column:
        st.markdown("#### SpO₂")
        render_vital_chart(dataframe, "spo2", "SpO₂", "%", (85, 100), (91, 93, 95), selected_patient)

    respiratory_column, blood_pressure_column = st.columns(2)

    with respiratory_column:
        st.markdown("#### Respiratory Rate")
        render_vital_chart(dataframe, "respiratory_rate", "Respiratory Rate", "breaths/min", (4, 32), (8, 11, 20, 24), selected_patient)

    with blood_pressure_column:
        st.markdown("#### Systolic Blood Pressure")
        render_vital_chart(dataframe, "systolic_bp", "Systolic Blood Pressure", "mmHg", (40, 240), (90, 100, 110, 220), selected_patient)

    st.markdown("#### Diastolic Blood Pressure")
    render_vital_chart(dataframe, "diastolic_bp", "Diastolic Blood Pressure", "mmHg", (30, 140), (), selected_patient)


def previous_snapshot(patient_id: str) -> dict[str, Any] | None:
    history = st.session_state.cohort_history.get(patient_id)
    if not history or len(history) < 2:
        return None
    return history[-2]


def format_delta(value: float | None, unit: str = "") -> str:
    if value is None:
        return "--"
    suffix = f" {unit}" if unit else ""
    return f"{value:+.0f}{suffix}"


def patient_freshness(age_seconds: float | None) -> tuple[str, str]:
    status = freshness_status(age_seconds, FRESH_EVENT_AGE_SECONDS, DELAYED_EVENT_AGE_SECONDS)
    return status, {"No data": "gray", "Current": "green", "Delayed": "orange", "Stale": "red"}[status]


def render_patient_cards(patient_ages: dict[str, float | None]) -> None:
    ranked_patients = sorted(
        PATIENT_IDS,
        key=lambda patient_id: (
            patient_freshness(patient_ages[patient_id])[0] not in {"Stale", "No data"},
            -patient_priority(st.session_state.cohort_vitals.get(patient_id, {}))[0],
            patient_id,
        ),
    )
    st.subheader("Patient Watchlist")

    for row_start in range(0, len(ranked_patients), 5):
        columns = st.columns(5)
        for column, patient_id in zip(columns, ranked_patients[row_start : row_start + 5], strict=False):
            vitals = st.session_state.cohort_vitals.get(patient_id, {})
            previous = previous_snapshot(patient_id)
            warning_score, priority = patient_priority(vitals)
            priority_color = {"Urgent": "red", "Review": "orange", "Stable": "green", "No data": "gray"}[priority]
            freshness, freshness_color = patient_freshness(patient_ages[patient_id])

            with column, st.container(border=True):
                score_label = "--" if warning_score < 0 else str(warning_score)
                st.markdown(f"**Patient {patient_id}** · :{priority_color}[{priority}] · :{freshness_color}[{freshness}]")
                st.caption(f"Vital warning score: {score_label}")
                st.markdown(
                    f"HR **{format_value(vitals.get('heart_rate'))}** bpm  \n"
                    f"SpO₂ **{format_value(vitals.get('spo2'))}**%  \n"
                    f"RR **{format_value(vitals.get('respiratory_rate'))}** /min  \n"
                    f"BP **{format_value(vitals.get('systolic_bp'))}/{format_value(vitals.get('diastolic_bp'))}**"
                )
                st.caption(
                    "Change: "
                    f"HR {format_delta(measurement_delta(vitals, previous, 'heart_rate'))} · "
                    f"SpO₂ {format_delta(measurement_delta(vitals, previous, 'spo2'))} · "
                    f"Data age {format_value(patient_ages[patient_id])} sec"
                )
                if st.button("View trends", key=f"focus-{patient_id}", width="stretch"):
                    st.session_state.selected_patient_id = patient_id
                    st.rerun()


def render_dashboard() -> None:
    if "selected_patient_id" not in st.session_state:
        st.session_state.selected_patient_id = None
    selected_patient = st.session_state.selected_patient_id
    priorities = [patient_priority(st.session_state.cohort_vitals.get(patient_id, {}))[1] for patient_id in PATIENT_IDS]
    patient_ages = {patient_id: event_age_seconds(st.session_state.cohort_vitals.get(patient_id, {})) for patient_id in PATIENT_IDS}
    freshness_states = {patient_id: patient_freshness(patient_ages[patient_id])[0] for patient_id in PATIENT_IDS}
    with st.session_state.connection_state_lock:
        connection_state = dict(st.session_state.connection_state)
    websocket_connections = sum(1 for state in connection_state.values() if state.get("connected"))
    current_patient_count = list(freshness_states.values()).count("Current")
    delayed_patient_count = list(freshness_states.values()).count("Delayed")
    stale_patient_count = len(PATIENT_IDS) - current_patient_count - delayed_patient_count

    st.title("Patient Monitoring")

    header_left, header_right = st.columns([4, 1])

    with header_left:
        st.caption(f"Adult acute-care cohort · {len(PATIENT_IDS)} patients")

    with header_right:
        if stale_patient_count == 0 and delayed_patient_count == 0:
            st.success("Live")
        elif stale_patient_count == 0:
            st.warning("Delayed")
        else:
            st.error("Stale")

    st.divider()

    tracked_column, urgent_column, review_column, freshness_column, websocket_column = st.columns(5)
    tracked_column.metric("Patients", len(PATIENT_IDS))
    urgent_column.metric("Urgent", priorities.count("Urgent"))
    review_column.metric("Review", priorities.count("Review"))
    freshness_column.metric("Current", f"{current_patient_count}/{len(PATIENT_IDS)}")
    websocket_column.metric("Live connections", f"{websocket_connections}/{len(PATIENT_IDS)}")

    render_patient_cards(patient_ages)

    st.divider()

    if selected_patient:
        vitals = st.session_state.cohort_vitals.get(selected_patient, {})
        focus_heading, clear_action = st.columns([5, 1])
        focus_heading.subheader(f"Focused Review · Patient {selected_patient}")
        if clear_action.button("Clear focus", width="stretch"):
            st.session_state.selected_patient_id = None
            st.rerun()

        heart_rate_column, spo2_column, respiratory_column, blood_pressure_column = st.columns(4)
        heart_rate_column.metric(label=f"Heart Rate · {heart_rate_status(vitals.get('heart_rate'))}", value=f"{format_value(vitals.get('heart_rate'))} bpm")
        spo2_column.metric(label=f"SpO₂ · {spo2_status(vitals.get('spo2'))}", value=f"{format_value(vitals.get('spo2'))} %")
        respiratory_column.metric(
            label=f"Respiratory Rate · {respiratory_rate_status(vitals.get('respiratory_rate'))}",
            value=f"{format_value(vitals.get('respiratory_rate'))} breaths/min",
        )
        blood_pressure_column.metric(label="Blood Pressure", value=f"{format_value(vitals.get('systolic_bp'))}/{format_value(vitals.get('diastolic_bp'))} mmHg")
        st.caption(
            f"Latest measurement {format_event_time(vitals.get('event_timestamp'))} · Oldest measurement age {format_value(patient_ages[selected_patient])} sec"
        )
        st.divider()

    freshness_column, latency_column = st.columns(2)
    freshness_column.metric(label="Delayed or stale", value=f"{delayed_patient_count + stale_patient_count}/{len(PATIENT_IDS)}")
    latencies = list(st.session_state.websocket_latency_ms.values())
    latency_column.metric(label="WebSocket Processing Latency", value=f"{format_value(sum(latencies) / len(latencies) if latencies else None)} ms")

    st.divider()

    render_trend_charts(selected_patient)

    websocket_errors = [patient_id for patient_id, state in connection_state.items() if state.get("error")]
    if websocket_errors:
        st.warning(f"WebSocket reconnecting for {len(websocket_errors)} patient connection(s).")

    if st.session_state.get("initial_load_error"):
        st.warning(f"Initial state request failed: {st.session_state.initial_load_error}")

    if st.session_state.get("api_refresh_error"):
        st.warning(f"Live state refresh failed: {st.session_state.api_refresh_error}")

    st.caption("Synthetic/research data for demonstration only. This dashboard is not intended for clinical decision-making.")


def main() -> None:
    st.set_page_config(page_title="Healthcare Realtime Monitoring", page_icon="🩺", layout="wide")
    start_websocket_workers()
    load_initial_state()
    process_websocket_messages()
    refresh_vitals_from_api()
    render_dashboard()
    time.sleep(REFRESH_INTERVAL_SECONDS)
    st.rerun()


if __name__ == "__main__":
    main()
