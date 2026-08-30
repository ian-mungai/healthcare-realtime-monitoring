import json
import os
import queue
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests
import streamlit as st
import websocket

from dashboard.aws_auth import get_sigv4_headers

PATIENT_ID = os.getenv("PATIENT_ID", "137506799")
API_ENDPOINT = os.environ["VITALS_API_ENDPOINT"].rstrip("/")
WEBSOCKET_URL = os.environ["VITALS_WEBSOCKET_URL"]
WEBSOCKET_SUBSCRIPTION_URL = f"{WEBSOCKET_URL}?{urlencode({'patient_id': PATIENT_ID})}"

REFRESH_INTERVAL_SECONDS = 0.5
HISTORY_SIZE = 60

st.set_page_config(page_title="Healthcare Realtime Monitoring", page_icon="🩺", layout="wide")


def get_initial_vitals(patient_id: str) -> dict[str, Any] | None:
    url = f"{API_ENDPOINT}/patients/{patient_id}/vitals"
    response = requests.get(url, headers=get_sigv4_headers(url), timeout=10)

    if response.status_code == 404:
        return None

    response.raise_for_status()

    return response.json()


def websocket_worker(message_queue: queue.Queue[dict[str, Any]], connection_state: dict[str, Any]) -> None:
    def on_open(_ws: websocket.WebSocketApp) -> None:
        connection_state["connected"] = True
        connection_state["error"] = None

    def on_message(_ws: websocket.WebSocketApp, message: str) -> None:
        try:
            payload = json.loads(message)

            if payload.get("patient_id") != PATIENT_ID:
                return

            payload["_received_at"] = datetime.now(UTC).isoformat()
            message_queue.put(payload)

        except json.JSONDecodeError as error:
            connection_state["error"] = f"Invalid WebSocket message: {error}"

    def on_error(_ws: websocket.WebSocketApp, error: Any) -> None:
        connection_state["connected"] = False
        connection_state["error"] = str(error)

    def on_close(_ws: websocket.WebSocketApp, _close_status_code: int | None, _close_message: str | None) -> None:
        connection_state["connected"] = False

    while True:
        try:
            signed_headers = get_sigv4_headers(WEBSOCKET_SUBSCRIPTION_URL)

            ws = websocket.WebSocketApp(
                WEBSOCKET_SUBSCRIPTION_URL,
                header=[f"{key}: {value}" for key, value in signed_headers.items()],
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            ws.run_forever()

        except Exception as error:
            connection_state["connected"] = False
            connection_state["error"] = str(error)

        time.sleep(3)


def start_websocket_thread() -> None:
    if "message_queue" not in st.session_state:
        st.session_state.message_queue = queue.Queue()

    if "connection_state" not in st.session_state:
        st.session_state.connection_state = {"connected": False, "error": None}

    if "websocket_thread" in st.session_state:
        return

    websocket_thread = threading.Thread(target=websocket_worker, args=(st.session_state.message_queue, st.session_state.connection_state), daemon=True)

    websocket_thread.start()
    st.session_state.websocket_thread = websocket_thread


def append_history(vitals: dict[str, Any]) -> None:
    event_timestamp = vitals.get("event_timestamp")

    if event_timestamp:
        try:
            timestamp = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

        except ValueError:
            timestamp = datetime.now(UTC)

    else:
        timestamp = datetime.now(UTC)

    st.session_state.vitals_history.append(
        {
            "timestamp": timestamp,
            "heart_rate": vitals.get("heart_rate"),
            "spo2": vitals.get("spo2"),
            "respiratory_rate": vitals.get("respiratory_rate"),
            "systolic_bp": vitals.get("systolic_bp"),
            "diastolic_bp": vitals.get("diastolic_bp"),
        }
    )


def load_initial_state() -> None:
    if "vitals_history" not in st.session_state:
        st.session_state.vitals_history = deque(maxlen=HISTORY_SIZE)

    if "vitals" in st.session_state:
        return

    try:
        vitals = get_initial_vitals(PATIENT_ID)

        if vitals:
            st.session_state.vitals = vitals
            append_history(vitals)

        else:
            st.session_state.vitals = {"patient_id": PATIENT_ID}

    except requests.RequestException as error:
        st.session_state.vitals = {"patient_id": PATIENT_ID}

        st.session_state.initial_load_error = str(error)


def process_websocket_messages() -> None:
    latest_payload = None

    while True:
        try:
            latest_payload = st.session_state.message_queue.get_nowait()

        except queue.Empty:
            break

    if not latest_payload:
        return

    received_at = latest_payload.pop("_received_at", None)

    st.session_state.vitals = latest_payload
    append_history(latest_payload)

    if received_at and latest_payload.get("event_timestamp"):
        received_time = datetime.fromisoformat(received_at)
        event_time = datetime.fromisoformat(latest_payload["event_timestamp"].replace("Z", "+00:00"))

        st.session_state.live_latency_ms = max((received_time - event_time).total_seconds() * 1000, 0.0)


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
    if not st.session_state.vitals_history:
        return pd.DataFrame()

    dataframe = pd.DataFrame(list(st.session_state.vitals_history))

    expected_columns = ["timestamp", "heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp"]

    for column in expected_columns:
        if column not in dataframe.columns:
            dataframe[column] = None

    dataframe["timestamp"] = pd.to_datetime(dataframe["timestamp"], utc=True)
    dataframe = dataframe.set_index("timestamp")

    return dataframe


def render_trend_charts() -> None:
    dataframe = history_dataframe()

    st.subheader("Live Trends")

    if dataframe.empty:
        st.info("Waiting for live vital events.")
        return

    heart_rate_column, spo2_column = st.columns(2)

    with heart_rate_column:
        st.markdown("#### Heart Rate")

        st.line_chart(dataframe[["heart_rate"]].rename(columns={"heart_rate": "Heart Rate (bpm)"}), width="stretch")

    with spo2_column:
        st.markdown("#### SpO₂")

        st.line_chart(dataframe[["spo2"]].rename(columns={"spo2": "SpO₂ (%)"}), width="stretch")

    respiratory_column, blood_pressure_column = st.columns(2)

    with respiratory_column:
        st.markdown("#### Respiratory Rate")

        st.line_chart(dataframe[["respiratory_rate"]].rename(columns={"respiratory_rate": "Respiratory Rate (breaths/min)"}), width="stretch")

    with blood_pressure_column:
        st.markdown("#### Blood Pressure")

        blood_pressure_dataframe = dataframe[["systolic_bp", "diastolic_bp"]].dropna(how="all")

        if blood_pressure_dataframe.empty:
            st.info("Waiting for blood pressure data.")

        else:
            st.line_chart(blood_pressure_dataframe.rename(columns={"systolic_bp": "Systolic (mmHg)", "diastolic_bp": "Diastolic (mmHg)"}), width="stretch")


def render_dashboard() -> None:
    vitals = st.session_state.vitals
    connection_state = st.session_state.connection_state

    st.title("Live Patient Vitals")

    header_left, header_right = st.columns([4, 1])

    with header_left:
        st.caption(f"Patient ID: {PATIENT_ID}")

    with header_right:
        if connection_state["connected"]:
            st.success("WebSocket Connected")

        else:
            st.error("WebSocket Disconnected")

    st.divider()

    heart_rate_column, spo2_column, respiratory_column, blood_pressure_column = st.columns(4)

    with heart_rate_column:
        st.metric(label=f"Heart Rate · {heart_rate_status(vitals.get('heart_rate'))}", value=f"{format_value(vitals.get('heart_rate'))} bpm")

    with spo2_column:
        st.metric(label=f"SpO₂ · {spo2_status(vitals.get('spo2'))}", value=f"{format_value(vitals.get('spo2'))} %")

    with respiratory_column:
        st.metric(
            label=f"Respiratory Rate · {respiratory_rate_status(vitals.get('respiratory_rate'))}",
            value=f"{format_value(vitals.get('respiratory_rate'))} breaths/min",
        )

    with blood_pressure_column:
        systolic = format_value(vitals.get("systolic_bp"))
        diastolic = format_value(vitals.get("diastolic_bp"))

        st.metric(label="Blood Pressure", value=f"{systolic}/{diastolic} mmHg")

    st.divider()

    updated_column, latency_column, source_column = st.columns(3)

    with updated_column:
        event_timestamp = vitals.get("event_timestamp")

        if event_timestamp:
            try:
                event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

                st.metric(label="Last Updated", value=event_time.astimezone().strftime("%Y-%m-%d %H:%M:%S"))

            except ValueError:
                st.metric(label="Last Updated", value=event_timestamp)

        else:
            st.metric(label="Last Updated", value="--")

    with latency_column:
        latency = st.session_state.get("live_latency_ms")

        st.metric(label="Live Processing Latency", value=f"{format_value(latency)} ms")

    with source_column:
        st.metric(label="Source Record", value=vitals.get("source_record_id", "--"))

    st.divider()

    render_trend_charts()

    if connection_state.get("error"):
        st.warning(f"WebSocket error: {connection_state['error']}")

    if st.session_state.get("initial_load_error"):
        st.warning(f"Initial state request failed: {st.session_state.initial_load_error}")

    st.caption("Synthetic/research data for demonstration only. This dashboard is not intended for clinical decision-making.")


start_websocket_thread()
load_initial_state()
process_websocket_messages()
render_dashboard()

time.sleep(REFRESH_INTERVAL_SECONDS)
st.rerun()
