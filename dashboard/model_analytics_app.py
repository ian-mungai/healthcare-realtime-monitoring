import os
from datetime import UTC, datetime
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.analytics import load_latest_predictions

RISK_LABELS = {
    "baseline_proxy": "Baseline proxy",
    "elevated_proxy": "Elevated proxy",
}
FEATURE_COLUMNS = {
    "heart_rate_mean": ("Mean heart rate", "bpm"),
    "respiratory_rate_mean": ("Mean respiratory rate", "/min"),
    "spo2_mean": ("Mean SpO₂", "%"),
    "systolic_bp_mean": ("Mean systolic BP", "mmHg"),
    "diastolic_bp_mean": ("Mean diastolic BP", "mmHg"),
}


@st.cache_data(ttl=300, show_spinner=False)
def get_model_predictions() -> list[dict[str, str | None]]:
    required = {
        name: os.getenv(name, "").strip()
        for name in (
            "AWS_REGION",
            "ATHENA_CATALOG",
            "ATHENA_WORKGROUP",
            "ATHENA_DBT_DATABASE",
            "DBT_ML_PREDICTIONS_LATEST_TABLE",
            "DBT_DIM_PATIENT_TABLE",
            "DBT_DIM_ENCOUNTER_TABLE",
            "DBT_ENCOUNTER_FEATURES_TABLE",
            "ATHENA_RESULTS_S3_URI",
        )
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing model analytics environment variables: {', '.join(missing)}")
    return load_latest_predictions(
        database=required["ATHENA_DBT_DATABASE"],
        predictions_table=required["DBT_ML_PREDICTIONS_LATEST_TABLE"],
        patient_table=required["DBT_DIM_PATIENT_TABLE"],
        encounter_table=required["DBT_DIM_ENCOUNTER_TABLE"],
        features_table=required["DBT_ENCOUNTER_FEATURES_TABLE"],
        output_location=required["ATHENA_RESULTS_S3_URI"],
        region=required["AWS_REGION"],
        catalog=required["ATHENA_CATALOG"],
        workgroup=required["ATHENA_WORKGROUP"],
    )


def format_scored_at(value: object) -> str:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(parsed):
        return "--"
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(UTC)
    return parsed.tz_convert(datetime.now().astimezone().tzinfo).strftime("%Y-%m-%d %H:%M:%S %Z")


def format_scored_at_compact(value: object) -> str:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(parsed):
        return "--"
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(UTC)
    return parsed.tz_convert(datetime.now().astimezone().tzinfo).strftime("%b %d · %H:%M")


def format_probability(value: Any) -> str:
    if pd.isna(value):
        return "--"
    probability = float(value)
    if 0 < probability < 0.001:
        return "<0.1%"
    return f"{probability:.1%}"


def prepare_predictions(predictions: list[dict[str, str | None]]) -> pd.DataFrame:
    dataframe = pd.DataFrame(predictions)
    if dataframe.empty:
        return dataframe

    numeric_columns = [
        "deterioration_probability",
        "decision_threshold",
        "feature_observation_count",
        *FEATURE_COLUMNS,
    ]
    for column in numeric_columns:
        dataframe[column] = pd.to_numeric(dataframe.get(column), errors="coerce")

    dataframe["patient_id"] = dataframe["patient_id"].str.rsplit("/", n=1).str[-1]
    dataframe["scored_at"] = pd.to_datetime(dataframe["scored_at"], utc=True, errors="coerce")
    dataframe["risk_label"] = dataframe["proxy_risk_band"].map(RISK_LABELS).fillna("Unclassified")
    dataframe["probability_label"] = dataframe["deterioration_probability"].map(format_probability)
    return dataframe.dropna(subset=["deterioration_probability", "patient_id", "scored_at"]).sort_values(
        ["deterioration_probability", "patient_id"], ascending=[False, True]
    )


def format_feature(value: Any, unit: str) -> str:
    if pd.isna(value):
        return "--"
    return f"{float(value):.1f} {unit}"


def is_clinically_validated(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def render_labeled_value(container: Any, label: str, value: str) -> None:
    container.caption(label)
    container.markdown(f"**{value}**")


def render_patient_reviews(dataframe: pd.DataFrame) -> None:
    st.subheader("Patient Score Review")
    columns = st.columns(2)
    for index, (_, row) in enumerate(dataframe.iterrows()):
        with columns[index % 2].container(border=True):
            heading_column, probability_column = st.columns([3, 1])
            heading_column.markdown(f"**Patient {row['patient_id']}**")
            probability_column.metric("Proxy probability", row["probability_label"])
            band_color = "red" if row["risk_label"] == "Elevated proxy" else "blue"
            st.markdown(f":{band_color}[**{row['risk_label']}**] · Encounter `{row['encounter_id']}`")

            first_feature_row = st.columns(3)
            second_feature_row = st.columns(2)
            feature_columns = [*first_feature_row, *second_feature_row]
            for feature_column, (field, (label, unit)) in zip(feature_columns, FEATURE_COLUMNS.items(), strict=True):
                render_labeled_value(feature_column, label, format_feature(row[field], unit))

            observation_count = row.get("feature_observation_count")
            count_label = "--" if pd.isna(observation_count) else f"{int(observation_count)}"
            st.caption(f"Feature-window observations: {count_label} · Scored {format_scored_at(row['scored_at'])}")


def render_dashboard() -> None:
    st.title("Synthetic Model Analytics")
    st.caption("Approved-model deterioration proxy · latest score per patient · refreshed at most every 5 minutes")

    try:
        predictions = get_model_predictions()
    except Exception as error:
        st.error(f"Model analytics unavailable: {error}")
        return

    if not predictions:
        st.info("No approved-model predictions are available.")
        return

    dataframe = prepare_predictions(predictions)
    if dataframe.empty:
        st.info("No valid approved-model predictions are available.")
        return

    elevated_count = int((dataframe["risk_label"] == "Elevated proxy").sum())
    latest_score = dataframe["scored_at"].max()
    score_age_hours = max((pd.Timestamp.now(tz=UTC) - latest_score).total_seconds() / 3600, 0.0)
    patient_count, elevated_column, baseline_column, freshness_column, scored_column = st.columns(5)
    patient_count.metric("Patients scored", len(dataframe))
    elevated_column.metric("Elevated proxy", elevated_count)
    baseline_column.metric("Baseline proxy", len(dataframe) - elevated_count)
    freshness_column.metric("Score age", f"{score_age_hours:.1f} hr")
    scored_column.metric("Latest score", format_scored_at_compact(latest_score))

    if score_age_hours >= 26:
        st.warning("Prediction freshness exceeds the 26-hour analytical contract.")
    else:
        st.success("Prediction freshness is within the 26-hour analytical contract.")

    st.subheader("Cohort Risk Ranking")
    decision_threshold = dataframe["decision_threshold"].dropna().iloc[0] if dataframe["decision_threshold"].notna().any() else 0.5

    bars = (
        alt.Chart(dataframe)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("deterioration_probability:Q", title="Deterioration proxy probability", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            y=alt.Y("patient_id:N", title="Patient", sort=dataframe["patient_id"].tolist()),
            color=alt.Color(
                "risk_label:N", title="Proxy band", scale=alt.Scale(domain=["Baseline proxy", "Elevated proxy"], range=["#2563eb", "#dc2626"])
            ),
            tooltip=[
                alt.Tooltip("patient_id:N", title="Patient"),
                alt.Tooltip("encounter_id:N", title="Encounter"),
                alt.Tooltip("deterioration_probability:Q", title="Probability", format=".1%"),
                alt.Tooltip("risk_label:N", title="Proxy band"),
                alt.Tooltip("model_version:N", title="Model"),
                alt.Tooltip("scored_at:T", title="Scored", format="%Y-%m-%d %H:%M:%S"),
            ],
        )
        .properties(height=max(340, len(dataframe) * 36))
    )
    probability_labels = bars.mark_text(align="left", baseline="middle", dx=4, color="#111827").encode(text="probability_label:N")
    threshold = (
        alt.Chart(pd.DataFrame({"threshold": [decision_threshold]}))
        .mark_rule(color="#475569", strokeDash=[5, 4], strokeWidth=2)
        .encode(x="threshold:Q")
    )
    st.altair_chart(bars + probability_labels + threshold, width="stretch")
    st.caption(f"Approved decision threshold: {decision_threshold:.1%}")

    model_version = str(dataframe["model_version"].iloc[0])
    feature_schema = str(dataframe["feature_schema_version"].iloc[0])
    label_definition = str(dataframe["label_definition_version"].iloc[0])
    prediction_scope = str(dataframe["prediction_scope"].iloc[0]).replace("_", " ").title()
    clinically_validated = any(is_clinically_validated(value) for value in dataframe["is_clinically_validated"])

    st.subheader("Model and Data Controls")
    model_column, threshold_column, feature_column, label_column, scope_column = st.columns(5)
    render_labeled_value(model_column, "Approved model", model_version)
    render_labeled_value(threshold_column, "Decision threshold", f"{decision_threshold:.1%}")
    render_labeled_value(feature_column, "Feature schema", feature_schema)
    render_labeled_value(label_column, "Label definition", label_definition)
    render_labeled_value(scope_column, "Prediction scope", prediction_scope)
    validation_label = "Yes" if clinically_validated else "No"
    st.warning(f"Clinically validated: {validation_label}. Synthetic portfolio demonstration only. Scores do not affect the live monitoring dashboard.")

    render_patient_reviews(dataframe)


def main() -> None:
    st.set_page_config(page_title="Healthcare Model Analytics", page_icon="📊", layout="wide")
    render_dashboard()


if __name__ == "__main__":
    main()
