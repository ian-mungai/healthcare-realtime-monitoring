"""Run the pre-specified analysis on one arm and apply the plan's decision rules (plans/analysis-plan.md, local).

analyze() fits every model out of fold, computes the AUCs with split-group bootstrap intervals, DeLong's test of each
model against NEWS2 with Holm's correction, the H1 and H3 GEE tests and the four sensitivity analyses, and returns
one JSON-ready result. decide() turns the primary statistics into the plan's H1, H2 and H3 decisions. The notebook
notebooks/model_comparison.ipynb calls analyze() and shows the result; e2e.analysis runs it for both arms.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from jobs.analysis import models, roc
from jobs.analysis.data import Frames

ALPHA = 0.05
SEED = 4817263
BOOTSTRAP_RESAMPLES = 2000
REFERENCE = "news2"
FITTED = ("naive_logistic", "gee_logistic", "gradient_boosting")


@dataclass(frozen=True)
class Comparison:
    difference: float
    p_value: float
    holm_p_value: float


@dataclass(frozen=True)
class Decisions:
    h1: bool
    h2: bool
    h2_models: tuple[str, ...]
    h3: bool
    h3_moderators: tuple[str, ...]


def decide(h1: models.JointTest, gee_interval: tuple[float, float], comparisons: dict[str, Comparison], moderation: dict[str, models.JointTest]) -> Decisions:
    """The plan's rules: H1 needs the Wald test and a GEE AUC interval above 0.5; H2 and H3 use Holm-adjusted p < 0.05."""
    h2_models = tuple(name for name, comparison in comparisons.items() if comparison.difference > 0 and comparison.holm_p_value < ALPHA)
    h3_moderators = tuple(name for name, test in moderation.items() if test.holm_p_value is not None and test.holm_p_value < ALPHA)
    return Decisions(
        h1=h1.p_value < ALPHA and gee_interval[0] > 0.5, h2=bool(h2_models), h2_models=h2_models, h3=bool(h3_moderators), h3_moderators=h3_moderators
    )


def compare(scores: pd.DataFrame) -> tuple[dict[str, roc.DeLong], dict[str, Comparison]]:
    """DeLong's test of each fitted model against NEWS2 on the same encounters, Holm-adjusted across the three."""
    labels = scores["label"].to_numpy()
    tests = {name: roc.delong(labels, scores[name].to_numpy(), scores[REFERENCE].to_numpy()) for name in FITTED}
    adjusted = multipletests([test.p_value for test in tests.values()], method="holm")[1]
    comparisons = {name: Comparison(test.difference, test.p_value, float(p)) for (name, test), p in zip(tests.items(), adjusted, strict=True)}
    return tests, comparisons


def evaluate(scores: pd.DataFrame, seed: int, resamples: int) -> dict[str, Any]:
    """AUCs, bootstrap intervals and DeLong comparisons of one set of encounter scores."""
    labels = scores["label"].to_numpy()
    names = (REFERENCE, *FITTED)
    boot = roc.bootstrap(labels, {name: scores[name].to_numpy() for name in names}, scores["split_group"].to_numpy(), REFERENCE, resamples, seed)
    tests, comparisons = compare(scores)
    return {
        "encounters": len(scores),
        "auc": {name: roc.auc(labels, scores[name].to_numpy()) for name in names},
        "auc_interval": boot.intervals,
        "difference_interval": boot.difference_intervals,
        "bootstrap": {"resamples": boot.resamples, "skipped": boot.skipped},
        "delong": {name: asdict(test) for name, test in tests.items()},
        "comparisons": {name: asdict(comparison) for name, comparison in comparisons.items()},
    }


def fixed_split_scores(frames: Frames, seed: int) -> pd.DataFrame:
    """Scores of the warehouse's test split from models fitted on its training split (sensitivity analysis 3)."""
    folds = pd.Series(np.where(frames.encounters["data_split"] == "test", 0, 1), index=frames.encounters.index)
    scores = models.out_of_fold_scores(frames.encounters, frames.minutes, folds, seed)
    return scores[scores["fold"] == 0]


def analyze(frames: Frames, seed: int = SEED, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Every pre-specified analysis of one arm, as JSON-ready values."""
    encounters, minutes = frames.encounters, frames.minutes
    folds = models.make_folds(encounters, seed)
    scores = models.out_of_fold_scores(encounters, minutes, folds, seed)
    primary = evaluate(scores, seed, resamples)
    h1 = models.vital_signal_test(minutes)
    moderation = models.moderation_tests(minutes)
    comparisons = {name: Comparison(**values) for name, values in primary["comparisons"].items()}
    decisions = decide(h1, primary["auc_interval"]["gee_logistic"], comparisons, moderation)
    fixed = fixed_split_scores(frames, seed)
    return {
        "analysis_set": {
            "encounters": len(encounters),
            "excluded_without_news2": frames.excluded_without_news2,
            "split_groups": int(encounters["split_group"].nunique()),
            "minute_rows": len(minutes),
            "deterioration_encounters": int(encounters["label"].sum()),
            "age_65_plus_encounters": int(encounters["age_65_plus"].sum()),
        },
        "primary": primary,
        "h1": asdict(h1),
        "h3": {name: asdict(test) for name, test in moderation.items()},
        "decisions": asdict(decisions),
        "sensitivity": {
            "encounter_clusters": {
                "h1": asdict(models.vital_signal_test(minutes, cluster="encounter_key")),
                "h3": {name: asdict(test) for name, test in models.moderation_tests(minutes, cluster="encounter_key", cov_type="robust").items()},
            },
            "fixed_split": evaluate(fixed, seed, resamples),
            "heart_rate_rise": {name: asdict(test) for name, test in models.rise_moderation_tests(minutes).items()},
        },
        "scores": scores.reset_index(names="encounter_key")[["encounter_key", "fold", "label", REFERENCE, *FITTED]].to_dict(orient="records"),
    }
