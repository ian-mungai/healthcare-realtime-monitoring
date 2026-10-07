"""Data shaping, folds and models of the analysis (plans/analysis-plan.md, Data, Models and Validation).

Failure modes (written before the code):

1. A 5-minute measure (systolic pressure, temperature, inhaled oxygen, ACVPU) is carried backward, or from one
   encounter into the next: carry forward only, within an encounter.
2. An admitting diagnosis or attending specialty falls outside the plan's groups or into two: every listed code has
   exactly one group, and an unknown code stops the analysis instead of joining "Other" silently.
3. The analysis runs on a plan that changed after it was frozen: a hash mismatch stops it before any data is read.
4. A split group lands in two folds, or an encounter is scored twice or never: each group sits in one test fold, each
   encounter gets exactly one out-of-fold score and every fold holds both classes.
5. Preprocessing learns from the test fold (scaling, imputation): changing one test encounter's values must not change
   another test encounter's score.
6. The minute models score an encounter from the wrong minute: the encounter score is the minute-14 prediction.
7. The moderation test counts the wrong terms: it tests only the moderator's three-way terms (levels minus one), and
   Holm adjusts across the three moderators.
8. A vital that only deteriorating encounters show (supplemental oxygen, new confusion) separates the labels and makes
   a Wald covariance singular: the H1 test of the 14 vital terms must still give a p-value (plan deviation 2).
9. The same separation makes the GEE prediction model diverge to missing scores: the minute models use the five
   continuous vitals, so every out-of-fold score is finite (plan deviation 3).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from jobs.analysis import data, models
from services.vitals_simulator.app.fhir.admission import ADMITTING_DIAGNOSES
from services.vitals_simulator.app.fhir.attending import load_roster
from testkit import expect

SEED = 4817263


def synthetic(encounters: int = 60, groups: int = 12, seed: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Encounter and minute frames shaped like the warehouse's, with a heart-rate trend in label-1 encounters."""
    rng = np.random.default_rng(seed)
    rows, minutes = [], []
    for number in range(encounters):
        key = f"e{number:03d}"
        label = number % 2
        group = f"g{number % groups:02d}"
        rows.append(
            {
                "encounter_key": key,
                "split_group": group,
                "label": label,
                "news2_total": int(rng.integers(0, 6)) + 2 * label,
                "age_65_plus": int(number % 3 == 0),
                # Groups change every two encounters, so each group holds both labels.
                "diagnosis_group": ["Cardiovascular", "Respiratory", "Infection and shock", "Other"][(number // 2) % 4],
                "specialty_group": ["Critical care and pulmonary", "Cardiology", "Hospital and internal medicine", "Other"][(number // 2 + 1) % 4],
                **{feature: rng.normal() + 0.5 * label for feature in models.ENCOUNTER_FEATURES},
            }
        )
        for minute in range(15):
            minutes.append(
                {
                    "encounter_key": key,
                    "split_group": group,
                    "label": label,
                    "minute_index": minute,
                    "age_65_plus": rows[-1]["age_65_plus"],
                    "diagnosis_group": rows[-1]["diagnosis_group"],
                    "specialty_group": rows[-1]["specialty_group"],
                    **{vital: rng.normal() + (0.2 * minute if vital == "heart_rate" and label else 0.0) for vital in models.MINUTE_VITALS},
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(minutes)


def test_five_minute_measures_carry_forward_within_an_encounter_only() -> None:
    minutes = pd.DataFrame(
        {
            "encounter_key": ["a"] * 4 + ["b"] * 2,
            "minute_index": [0, 1, 2, 3, 0, 1],
            "temperature": [np.nan, 37.0, np.nan, np.nan, np.nan, 36.5],
            "heart_rate": [80.0, np.nan, 82.0, 83.0, 70.0, 71.0],
        }
    )

    filled = data.carry_forward(minutes, ("temperature",))

    expect.equal(filled["temperature"].tolist()[:4][1:], [37.0, 37.0, 37.0])
    expect.equal(bool(np.isnan(filled["temperature"].iloc[0])), True)
    expect.equal(bool(np.isnan(filled["temperature"].iloc[4])), True)
    expect.equal(bool(np.isnan(filled["heart_rate"].iloc[1])), True)


def test_every_listed_code_has_exactly_one_group() -> None:
    expect.equal({code for code in ADMITTING_DIAGNOSES if data.diagnosis_group(code) not in data.DIAGNOSIS_GROUPS}, set())
    expect.equal({version.taxonomy_code for version in load_roster() if data.specialty_group(version.taxonomy_code) not in data.SPECIALTY_GROUPS}, set())
    with pytest.raises(data.AnalysisError, match="999999"):
        data.diagnosis_group("999999")
    with pytest.raises(data.AnalysisError, match="207X00000X"):
        data.specialty_group("207X00000X")


def test_a_changed_plan_stops_the_analysis(tmp_path: Path) -> None:
    plan = tmp_path / "analysis-plan.md"
    plan.write_text("frozen\n", encoding="utf-8")
    frozen = hashlib.sha256(b"frozen\n").hexdigest()

    data.check_plan(plan, frozen)
    plan.write_text("changed\n", encoding="utf-8")

    with pytest.raises(data.AnalysisError, match="plan"):
        data.check_plan(plan, frozen)


def test_each_group_sits_in_one_test_fold_and_every_encounter_is_scored_once() -> None:
    encounters, minutes = synthetic()

    folds = models.make_folds(encounters, seed=SEED)
    scores = models.out_of_fold_scores(encounters, minutes, folds, seed=SEED)

    expect.equal(int(encounters.assign(fold=folds.values).groupby("split_group")["fold"].nunique().max()), 1)
    expect.equal(sorted(scores.index), sorted(encounters["encounter_key"]))
    expect.equal(set(scores.columns) >= {"news2", "naive_logistic", "gee_logistic", "gradient_boosting"}, True)
    by_fold = encounters.assign(fold=folds.values).groupby("fold")["label"].nunique()
    expect.equal(int(by_fold.min()), 2)


def test_preprocessing_never_learns_from_the_test_fold() -> None:
    encounters, minutes = synthetic()
    folds = models.make_folds(encounters, seed=SEED)
    baseline = models.out_of_fold_scores(encounters, minutes, folds, seed=SEED)
    test_keys = encounters.loc[folds.values == 0, "encounter_key"].tolist()
    changed, other = test_keys[0], test_keys[1]
    shifted_minutes = minutes.copy()
    shifted_minutes.loc[shifted_minutes["encounter_key"] == changed, list(models.MINUTE_VITALS)] += 1000.0
    shifted_encounters = encounters.copy()
    shifted_encounters.loc[shifted_encounters["encounter_key"] == changed, list(models.ENCOUNTER_FEATURES)] += 1000.0

    shifted = models.out_of_fold_scores(shifted_encounters, shifted_minutes, folds, seed=SEED)

    for model in ("naive_logistic", "gee_logistic", "gradient_boosting"):
        expect.equal(round(float(shifted.loc[other, model]), 12), round(float(baseline.loc[other, model]), 12), f"{model} score of another test encounter")


def test_minute_models_score_the_last_minute() -> None:
    _, minutes = synthetic()

    rows = models.scoring_rows(minutes)

    expect.equal(set(rows["minute_index"]), {14})
    expect.equal(len(rows), minutes["encounter_key"].nunique())


def test_the_moderation_test_counts_only_three_way_terms_and_adjusts_with_holm() -> None:
    _, minutes = synthetic()

    results = models.moderation_tests(minutes, cluster="split_group")

    expect.equal({name: result.degrees_of_freedom for name, result in results.items()}, {"age_65_plus": 1, "diagnosis_group": 3, "specialty_group": 3})
    raw = sorted(result.p_value for result in results.values())
    adjusted = sorted(result.holm_p_value for result in results.values() if result.holm_p_value is not None)
    expect.equal(len(adjusted), 3)
    expect.equal(round(adjusted[0], 12), round(min(1.0, raw[0] * 3), 12))


def with_separating_events(minutes: pd.DataFrame) -> pd.DataFrame:
    """As planted: oxygen in some deteriorating encounters and new confusion in fewer, both from mid-window."""
    separating = minutes.copy()
    number = separating["encounter_key"].str[1:].astype(int)
    later = separating["minute_index"] >= 7
    separating["inhaled_oxygen_concentration"] = np.where((separating["label"] == 1) & (number % 3 == 1) & later, 24.0, 21.0)
    separating["consciousness_level"] = np.where((separating["label"] == 1) & (number % 5 == 1) & later, 1.0, 0.0)
    return separating


def test_the_vital_signal_test_survives_a_separating_vital() -> None:
    _, minutes = synthetic()

    result = models.vital_signal_test(with_separating_events(minutes))

    expect.equal(result.degrees_of_freedom, 14)
    if not 0.0 <= result.p_value <= 1.0:
        expect.fail(f"expected: a p-value despite separation, got {result}")


def test_minute_models_score_every_encounter_despite_separating_events() -> None:
    encounters, minutes = synthetic()
    folds = models.make_folds(encounters, seed=SEED)

    scores = models.out_of_fold_scores(encounters, with_separating_events(minutes), folds, seed=SEED)

    expect.equal(int(scores[["naive_logistic", "gee_logistic"]].isna().sum().sum()), 0)
