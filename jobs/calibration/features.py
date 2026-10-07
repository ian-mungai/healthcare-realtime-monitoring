"""Encounter features computed from batch records, matching the warehouse's vital-features-v3, plus feature-window NEWS2.

The definitions follow dbt's fact_encounter_vital_features: the feature window is the 15 minutes from the encounter's
first reading; means, minimums, maximums and the sample standard deviation are taken over readings in that window, and
a vital without a reading stays missing. NEWS2 scores the last value of each parameter before the window ends.
"""

from datetime import datetime, timedelta
from statistics import mean, stdev
from typing import Any

from services.news2 import PARAMETERS, news2_score
from services.vitals_simulator.app.simulation.scenario import FEATURE_WINDOW_SECONDS

# (column, field, statistic) in the order of the warehouse's ml_training_dataset.
FEATURES = (
    ("heart_rate_mean", "heart_rate", "mean"),
    ("heart_rate_min", "heart_rate", "min"),
    ("heart_rate_max", "heart_rate", "max"),
    ("heart_rate_stddev", "heart_rate", "stddev"),
    ("respiratory_rate_mean", "respiratory_rate", "mean"),
    ("respiratory_rate_min", "respiratory_rate", "min"),
    ("respiratory_rate_max", "respiratory_rate", "max"),
    ("spo2_mean", "spo2", "mean"),
    ("spo2_min", "spo2", "min"),
    ("systolic_bp_mean", "systolic_bp", "mean"),
    ("systolic_bp_min", "systolic_bp", "min"),
    ("diastolic_bp_mean", "diastolic_bp", "mean"),
    ("temperature_mean", "temperature", "mean"),
    ("temperature_max", "temperature", "max"),
    ("inhaled_oxygen_concentration_max", "inhaled_oxygen_concentration", "max"),
    ("consciousness_level_max", "consciousness_level", "max"),
)
FEATURE_COLUMNS = tuple(column for column, _field, _statistic in FEATURES)


def _statistic(values: list[float], statistic: str) -> float | None:
    if not values:
        return None
    if statistic == "stddev":
        return stdev(values) if len(values) > 1 else None
    if statistic == "mean":
        return mean(values)
    return min(values) if statistic == "min" else max(values)


def encounter_features(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The 16 v3 features and the feature-window NEWS2 of one encounter's records."""
    timed = sorted(((datetime.fromisoformat(record["event_timestamp"]), record) for record in records), key=lambda pair: pair[0])
    if not timed:
        return dict.fromkeys((*FEATURE_COLUMNS, "news2"))
    cutoff = timed[0][0] + timedelta(seconds=FEATURE_WINDOW_SECONDS)
    window = [record for when, record in timed if when < cutoff]
    values: dict[str, list[float]] = {}
    latest: dict[str, float] = {}
    for record in window:
        for field in {field for _column, field, _statistic in FEATURES} | set(PARAMETERS):
            if record.get(field) is not None:
                values.setdefault(field, []).append(float(record[field]))
                latest[field] = float(record[field])
    features: dict[str, Any] = {column: _statistic(values.get(field, []), statistic) for column, field, statistic in FEATURES}
    features["news2"] = news2_score(latest)
    return features
