"""Calibration features computed from batch records, the same as the warehouse's vital-features-v3.

Failure modes (written before the code):

1. A reading from the outcome window leaks into the features: only readings before 15 minutes after the encounter's
   first reading count, as in dbt's fact_encounter_vital_features.
2. A statistic differs from dbt's: means, minimums, maximums and the sample standard deviation match the SQL.
3. A vital with no reading in the window gets 0 instead of a missing value: it stays None.
4. NEWS2 uses stale values: it scores the last value of each parameter before the window ends.
5. Several records share a timestamp (an observation set): they are all used, in any order (found by the e2e run).
"""

from datetime import UTC, datetime, timedelta

from jobs.calibration.features import FEATURE_COLUMNS, encounter_features
from testkit import expect

START = datetime(2026, 6, 1, 8, tzinfo=UTC)


def record(seconds: int, **values: float) -> dict:
    return {"event_timestamp": (START + timedelta(seconds=seconds)).isoformat(), "encounter_id": "encounter-1", **values}


def test_features_use_the_feature_window_only_and_match_the_sql_statistics() -> None:
    records = [
        record(0, heart_rate=80.0, respiratory_rate=14.0),
        record(300, heart_rate=90.0, systolic_bp=120.0, diastolic_bp=80.0, temperature=36.8, inhaled_oxygen_concentration=21.0, consciousness_level=0),
        record(600, heart_rate=100.0, systolic_bp=110.0, diastolic_bp=70.0, temperature=37.2, inhaled_oxygen_concentration=24.0, consciousness_level=1),
        record(900, heart_rate=135.0, respiratory_rate=28.0),
    ]

    features = encounter_features(records)

    expect.equal(len(FEATURE_COLUMNS), 16)
    expect.equal((features["heart_rate_mean"], features["heart_rate_min"], features["heart_rate_max"]), (90.0, 80.0, 100.0))
    expect.equal(round(features["heart_rate_stddev"], 6), 10.0)
    expect.equal((features["respiratory_rate_max"], features["systolic_bp_min"], features["temperature_max"]), (14.0, 110.0, 37.2))
    expect.equal((features["inhaled_oxygen_concentration_max"], features["consciousness_level_max"]), (24.0, 1.0))
    expect.equal((features["spo2_mean"], features["spo2_min"]), (None, None))


def test_news2_scores_the_last_values_before_the_window_ends() -> None:
    records = [
        record(0, heart_rate=120.0, respiratory_rate=22.0, spo2=97.0),
        record(600, systolic_bp=105.0, temperature=36.9, inhaled_oxygen_concentration=21.0, consciousness_level=0),
        record(899, heart_rate=95.0, respiratory_rate=18.0, spo2=94.0),
        record(900, heart_rate=135.0, respiratory_rate=28.0, spo2=89.0),
    ]

    expect.equal(encounter_features(records)["news2"], 1 + 1 + 1)


def test_records_sharing_a_timestamp_are_all_used() -> None:
    records = [record(0, heart_rate=80.0), record(0, systolic_bp=120.0), record(0, temperature=36.8)]

    features = encounter_features(records)

    expect.equal((features["heart_rate_mean"], features["systolic_bp_mean"], features["temperature_mean"]), (80.0, 120.0, 36.8))
