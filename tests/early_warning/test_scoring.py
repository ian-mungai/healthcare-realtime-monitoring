"""Real-time early-warning scoring: the published model scored in plain Python on the live feature window, and NEWS2.

The endpoint scores an encounter once its 15-minute feature window has closed, from the readings the stream processor
kept, so its score must equal the batch score the warehouse features give for the same readings.

Failure modes (written before the code):

1. The plain-Python score differs from scikit-learn's for the same features: a different imputation, scaling or
   coefficient order. Parity is checked against a fitted training pipeline, with a missing feature.
2. The window differs from dbt's (fact_encounter_vital_features): it starts at the encounter's first reading and keeps
   readings strictly before start + 15 minutes; a reading at the cutoff is outside.
3. The standard deviation uses the population formula, or one reading gives 0: dbt's stddev_samp gives None for one
   reading, which the model then imputes.
4. A vital with no reading in the window scores as 0 instead of being imputed with the training median.
5. Feature names, their order or the window length drift from the training job and dbt: checked against
   jobs/ml/train_logistic_regression.FEATURE_COLUMNS and dbt_project.yml.
6. Parameters for another feature order are applied silently: scoring stops.
7. NEWS2 with a missing parameter scores as normal: the total is None and the missing parameters are named; the band
   follows the RCP 2017 thresholds, including a single parameter scoring 3.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jobs.ml import train_logistic_regression as training
from services.early_warning import scoring
from testkit import expect

ROOT = Path(__file__).resolve().parents[2]
START = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def reading(seconds: float, **vitals: float) -> dict:
    return {"event_timestamp": (START + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"), **vitals}


def fitted_parameters() -> tuple[Any, dict[str, Any]]:
    generator = np.random.default_rng(7)
    records = []
    for index in range(80):
        label = index % 2
        record: dict[str, Any] = {column: float(generator.normal(80 + 10 * label, 5)) for column in training.FEATURE_COLUMNS}
        record.update(
            encounter_key=f"e{index}",
            patient_key=f"p{index}",
            data_split="test" if index >= 72 else "train",
            feature_schema_version="vital-features-v3",
            label_definition_version="v2",
            deterioration_proxy_label=label,
        )
        records.append(record)
    records[3]["spo2_min"] = None
    model, manifest = training.train_baseline(records)
    return model, training.scoring_parameters(model, manifest)


def test_the_plain_python_score_equals_the_training_pipeline() -> None:
    model, parameters = fitted_parameters()
    generator = np.random.default_rng(11)
    for _ in range(20):
        features: dict[str, float | None] = {column: float(generator.normal(85, 8)) for column in training.FEATURE_COLUMNS}
        features["diastolic_bp_mean"] = None
        expected = model.predict_proba([[math.nan if features[column] is None else features[column] for column in training.FEATURE_COLUMNS]])[0][1]
        expect.equal(abs(scoring.probability(features, parameters) - expected) < 1e-12, True, f"{scoring.probability(features, parameters)} != {expected}")


def test_the_window_starts_at_the_first_reading_and_excludes_the_cutoff() -> None:
    readings = [
        reading(900, heart_rate=200),
        reading(0, heart_rate=60, respiratory_rate=12, spo2=97),
        reading(899.999, heart_rate=100, spo2=95),
        reading(300, systolic_bp=120, diastolic_bp=80),
    ]

    window = scoring.window_features(readings)

    expect.equal(window.start, START)
    expect.equal(window.features["heart_rate_max"], 100.0)
    expect.equal(window.features["heart_rate_mean"], 80.0)
    expect.equal(window.features["heart_rate_stddev"], math.sqrt(800.0))
    expect.equal(window.features["spo2_min"], 95.0)
    expect.equal(window.features["systolic_bp_min"], 120.0)


def test_one_reading_has_no_standard_deviation_and_a_missing_vital_is_none() -> None:
    window = scoring.window_features([reading(0, heart_rate=70)])

    expect.equal(window.features["heart_rate_stddev"], None)
    expect.equal(window.features["respiratory_rate_mean"], None)


def test_the_window_matches_the_training_features_and_dbt() -> None:
    expect.equal(tuple(scoring.FEATURES), training.FEATURE_COLUMNS)
    text = (ROOT / "dbt" / "dbt_project.yml").read_text(encoding="utf-8")
    match = re.search(r"feature_window_minutes: (\d+)", text)
    expect.not_equal(match, None, "dbt_project.yml has no feature_window_minutes")
    minutes = int(match.group(1)) if match else 0
    expect.equal(scoring.WINDOW, timedelta(minutes=minutes))


def test_parameters_for_another_feature_order_stop_scoring() -> None:
    _, parameters = fitted_parameters()
    parameters["feature_columns"] = list(reversed(parameters["feature_columns"]))
    with pytest.raises(scoring.ScoringError, match="feature"):
        scoring.probability(dict.fromkeys(training.FEATURE_COLUMNS, 1.0), parameters)


def test_news2_names_missing_parameters_and_follows_the_rcp_bands() -> None:
    complete = {
        "respiratory_rate": 16,
        "spo2": 97,
        "inhaled_oxygen_concentration": 21,
        "systolic_bp": 120,
        "heart_rate": 70,
        "consciousness_level": 0,
        "temperature": 37.0,
    }
    expect.equal(scoring.news2_summary(complete)["band"], "low")
    expect.equal(scoring.news2_summary({**complete, "heart_rate": 135})["band"], "low-medium")
    expect.equal(scoring.news2_summary({**complete, "respiratory_rate": 22, "spo2": 93, "heart_rate": 95})["band"], "medium")
    expect.equal(scoring.news2_summary({**complete, "respiratory_rate": 26, "spo2": 90, "heart_rate": 95})["total"], 7)
    expect.equal(scoring.news2_summary({**complete, "respiratory_rate": 26, "spo2": 90, "heart_rate": 95})["band"], "high")

    partial = scoring.news2_summary({key: value for key, value in complete.items() if key != "temperature"})

    expect.equal((partial["total"], partial["band"], partial["missing"]), (None, None, ["temperature"]))
    expect.equal(partial["scores"]["heart_rate"], 0)
