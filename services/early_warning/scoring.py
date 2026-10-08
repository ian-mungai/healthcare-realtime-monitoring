"""Early-warning scores for one patient from the live cache: NEWS2 now, and the published model at window close.

The model is the logistic baseline of jobs/ml/train_logistic_regression.py, scored here in plain Python from the
parameters training publishes (scoring_parameters.json), so the Lambda needs no scikit-learn. Its features are those of
dbt's fact_encounter_vital_features over the encounter's feature window: from the first reading to 15 minutes later,
the cutoff excluded. The endpoint scores an encounter only once that window has closed, as training saw it. Failure
modes: tests/early_warning/test_scoring.py.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.news2 import PARAMETERS, news2_parameter_score
else:
    try:
        from services.news2 import PARAMETERS, news2_parameter_score
    except ModuleNotFoundError:
        from news2 import PARAMETERS, news2_parameter_score

# dbt_project.yml feature_window_minutes.
WINDOW = timedelta(minutes=15)


def _sample_stddev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


STATISTICS: dict[str, Callable[[list[float]], float | None]] = {
    "mean": lambda values: statistics.fmean(values),
    "min": min,
    "max": max,
    "stddev": _sample_stddev,
}
# Each model feature as (vital, statistic), in the training job's column order.
FEATURES: dict[str, tuple[str, str]] = {
    "heart_rate_mean": ("heart_rate", "mean"),
    "heart_rate_min": ("heart_rate", "min"),
    "heart_rate_max": ("heart_rate", "max"),
    "heart_rate_stddev": ("heart_rate", "stddev"),
    "respiratory_rate_mean": ("respiratory_rate", "mean"),
    "respiratory_rate_min": ("respiratory_rate", "min"),
    "respiratory_rate_max": ("respiratory_rate", "max"),
    "spo2_mean": ("spo2", "mean"),
    "spo2_min": ("spo2", "min"),
    "systolic_bp_mean": ("systolic_bp", "mean"),
    "systolic_bp_min": ("systolic_bp", "min"),
    "diastolic_bp_mean": ("diastolic_bp", "mean"),
}


class ScoringError(ValueError):
    """The published parameters cannot score these features."""


@dataclass(frozen=True)
class Window:
    start: datetime
    cutoff: datetime
    readings: int
    features: dict[str, float | None]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def window_features(readings: Iterable[Mapping[str, Any]]) -> Window:
    """The model features over the feature window of an encounter's readings, as dbt computes them."""
    timed = sorted(((parse_time(str(item["event_timestamp"])), item) for item in readings), key=lambda pair: pair[0])
    if not timed:
        raise ScoringError("the encounter has no readings")
    start = timed[0][0]
    cutoff = start + WINDOW
    inside = [item for moment, item in timed if moment < cutoff]
    values = {vital: [float(item[vital]) for item in inside if item.get(vital) is not None] for vital, _ in FEATURES.values()}
    features = {name: STATISTICS[statistic](values[vital]) if values[vital] else None for name, (vital, statistic) in FEATURES.items()}
    return Window(start=start, cutoff=cutoff, readings=len(inside), features=features)


def probability(features: Mapping[str, float | None], parameters: Mapping[str, Any]) -> float:
    """The published model's probability: median imputation, standard scaling, then the logistic function."""
    if list(parameters["feature_columns"]) != list(FEATURES):
        raise ScoringError(f"the parameters' feature order {parameters['feature_columns']} is not the live window's")
    logit = float(parameters["intercept"])
    for name, median, mean, scale, coefficient in zip(
        FEATURES, parameters["medians"], parameters["means"], parameters["scales"], parameters["coefficients"], strict=True
    ):
        value = features.get(name)
        observed = float(median) if value is None or math.isnan(value) else float(value)
        logit += float(coefficient) * (observed - float(mean)) / float(scale)
    return 1.0 / (1.0 + math.exp(-logit))


def news2_summary(vitals: Mapping[str, Any]) -> dict[str, Any]:
    """Each NEWS2 parameter's score, the total and the RCP 2017 risk band; with a parameter missing, no total."""
    scores = {name: news2_parameter_score(name, float(vitals[name])) for name in PARAMETERS if vitals.get(name) is not None}
    missing = [name for name in PARAMETERS if name not in scores]
    if missing:
        return {"scores": scores, "total": None, "band": None, "missing": missing}
    total = sum(scores.values())
    if total >= 7:
        band = "high"
    elif total >= 5:
        band = "medium"
    elif max(scores.values()) == 3:
        band = "low-medium"
    else:
        band = "low"
    return {"scores": scores, "total": total, "band": band, "missing": []}
