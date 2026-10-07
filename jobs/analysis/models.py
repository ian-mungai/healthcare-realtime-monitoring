"""The plan's four models, its folds and its GEE tests (plans/analysis-plan.md, Models, Validation and Tests).

1. NEWS2: the warehouse's feature-window total, no fitting.
2. Naive logistic regression and 3. the GEE logistic model share one mean model on the minute rows:
   logit P(label) = b0 + sum b_v z_v(t) + c t + sum g_v z_v(t) t, with z_v the vitals standardized and imputed on the
   training fold and t the minute index. The naive model treats minute rows as independent; the GEE model clusters
   them by encounter with an exchangeable working correlation. Each scores an encounter by its minute-14 prediction.
4. Gradient-boosted trees on the encounter features (vital-features-v3 plus the five slopes), with fixed settings.

Folds are StratifiedGroupKFold by split group. The H1 test refits the GEE mean model on the whole analysis set; the
H3 tests fit one linear GEE per moderator on the heart-rate minute means. Both cluster by split group with the
bias-reduced (Mancl and DeRouen) covariance unless a sensitivity analysis asks otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedGroupKFold
from statsmodels.stats.multitest import multipletests

from jobs.analysis.data import DIAGNOSIS_GROUPS, MODERATORS, SLOPE_COLUMNS, SPECIALTY_GROUPS
from jobs.calibration.features import FEATURE_COLUMNS

MINUTE_VITALS = ("heart_rate", "respiratory_rate", "spo2", "systolic_bp", "temperature", "inhaled_oxygen_concentration", "consciousness_level")
ENCOUNTER_FEATURES = (*FEATURE_COLUMNS, *SLOPE_COLUMNS)
SCORING_MINUTE = 14
FOLDS = 5
GRADIENT_BOOSTING = {"learning_rate": 0.05, "max_iter": 200, "max_leaf_nodes": 15, "min_samples_leaf": 20, "l2_regularization": 1.0}
MODERATOR_LEVELS = {"age_65_plus": (0, 1), "diagnosis_group": DIAGNOSIS_GROUPS, "specialty_group": SPECIALTY_GROUPS}


@dataclass(frozen=True)
class WaldTest:
    statistic: float
    degrees_of_freedom: int
    p_value: float
    holm_p_value: float | None = None
    estimates: tuple[float, ...] = ()


@dataclass(frozen=True)
class Scaling:
    medians: pd.Series
    means: pd.Series
    deviations: pd.Series


def make_folds(encounters: pd.DataFrame, seed: int, n_splits: int = FOLDS) -> pd.Series:
    """Each encounter's test fold, positionally aligned with the frame; a split group never spans two folds."""
    folds = np.full(len(encounters), -1)
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for fold, (_train, test) in enumerate(splitter.split(encounters, encounters["label"], encounters["split_group"])):
        folds[test] = fold
    return pd.Series(folds, index=encounters.index, name="fold")


def fit_scaling(minutes: pd.DataFrame) -> Scaling:
    values = minutes[list(MINUTE_VITALS)]
    medians = values.median()
    filled = values.fillna(medians)
    deviations = filled.std(ddof=0).replace(0.0, 1.0)
    return Scaling(medians=medians, means=filled.mean(), deviations=deviations)


def minute_design(minutes: pd.DataFrame, scaling: Scaling) -> np.ndarray:
    """Intercept, standardized vitals, minute index and vital-by-minute interactions, in that order."""
    z = ((minutes[list(MINUTE_VITALS)].fillna(scaling.medians) - scaling.means) / scaling.deviations).to_numpy()
    t = minutes["minute_index"].to_numpy(dtype=float)[:, None]
    return np.hstack([np.ones((len(minutes), 1)), z, t, z * t])


def scoring_rows(minutes: pd.DataFrame) -> pd.DataFrame:
    """The minute each minute model scores an encounter from: the last minute of the feature window."""
    return minutes[minutes["minute_index"] == SCORING_MINUTE]


def _minute_scores(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    scaling = fit_scaling(train)
    exog = minute_design(train, scaling)
    naive = sm.GLM(train["label"].to_numpy(), exog, family=sm.families.Binomial()).fit()
    gee = sm.GEE(
        train["label"].to_numpy(), exog, groups=train["encounter_key"].to_numpy(), family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()
    ).fit()
    rows = scoring_rows(test)
    design = minute_design(rows, scaling)
    index = rows["encounter_key"].to_numpy()
    return pd.Series(naive.predict(design), index=index), pd.Series(gee.predict(design), index=index)


def out_of_fold_scores(encounters: pd.DataFrame, minutes: pd.DataFrame, folds: pd.Series, seed: int) -> pd.DataFrame:
    """Every encounter's score from each model, each fitted on the other folds; NEWS2 needs no fitting."""
    frames = []
    for fold in sorted(set(folds)):
        test_keys = set(encounters.loc[folds.to_numpy() == fold, "encounter_key"])
        train_encounters = encounters[~encounters["encounter_key"].isin(test_keys)]
        test_encounters = encounters[encounters["encounter_key"].isin(test_keys)]
        naive, gee = _minute_scores(minutes[~minutes["encounter_key"].isin(test_keys)], minutes[minutes["encounter_key"].isin(test_keys)])
        trees = HistGradientBoostingClassifier(**GRADIENT_BOOSTING, random_state=seed)
        trees.fit(train_encounters[list(ENCOUNTER_FEATURES)], train_encounters["label"])
        boosted = pd.Series(trees.predict_proba(test_encounters[list(ENCOUNTER_FEATURES)])[:, 1], index=test_encounters["encounter_key"].to_numpy())
        frames.append(pd.DataFrame({"naive_logistic": naive, "gee_logistic": gee, "gradient_boosting": boosted}).assign(fold=fold))
    scores = pd.concat(frames)
    base = encounters.set_index("encounter_key")[["label", "split_group", "news2_total"]].rename(columns={"news2_total": "news2"})
    return base.join(scores, how="inner")


def _wald(result: sm.regression.linear_model.RegressionResults, columns: list[int]) -> WaldTest:
    restriction = np.zeros((len(columns), len(result.params)))
    for row, column in enumerate(columns):
        restriction[row, column] = 1.0
    test = result.wald_test(restriction, scalar=True)
    return WaldTest(
        statistic=float(test.statistic),
        degrees_of_freedom=len(columns),
        p_value=float(test.pvalue),
        estimates=tuple(float(result.params[column]) for column in columns),
    )


def vital_signal_test(minutes: pd.DataFrame, cluster: str = "split_group", cov_type: str = "bias_reduced") -> WaldTest:
    """H1 (a): the joint Wald test of the 14 vital terms of the GEE mean model, on the whole analysis set."""
    exog = minute_design(minutes, fit_scaling(minutes))
    result = sm.GEE(
        minutes["label"].to_numpy(), exog, groups=minutes[cluster].to_numpy(), family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()
    ).fit(cov_type=cov_type)
    vitals = len(MINUTE_VITALS)
    return _wald(result, [*range(1, 1 + vitals), *range(2 + vitals, 2 + 2 * vitals)])


def moderator_dummies(values: pd.Series, moderator: str) -> pd.DataFrame:
    """One indicator per non-reference level present; the reference is the plan's first level."""
    levels = [level for level in MODERATOR_LEVELS[moderator][1:] if (values == level).any()]
    return pd.DataFrame({f"{moderator}={level}": (values == level).astype(float).to_numpy() for level in levels})


def moderation_test(minutes: pd.DataFrame, moderator: str, cluster: str = "split_group", cov_type: str = "bias_reduced") -> WaldTest:
    """H3 for one moderator: heart-rate minute mean on minute, label, moderator and all their interactions."""
    rows = minutes[minutes["heart_rate"].notna()]
    t = rows["minute_index"].to_numpy(dtype=float)
    label = rows["label"].to_numpy(dtype=float)
    dummies = moderator_dummies(rows[moderator], moderator).to_numpy()
    k = dummies.shape[1]
    exog = np.hstack(
        [
            np.ones((len(rows), 1)),
            t[:, None],
            label[:, None],
            dummies,
            (t * label)[:, None],
            dummies * t[:, None],
            dummies * label[:, None],
            dummies * (t * label)[:, None],
        ]
    )
    result = sm.GEE(
        rows["heart_rate"].to_numpy(), exog, groups=rows[cluster].to_numpy(), family=sm.families.Gaussian(), cov_struct=sm.cov_struct.Exchangeable()
    ).fit(cov_type=cov_type)
    first = 4 + 3 * k
    return _wald(result, list(range(first, first + k)))


def moderation_tests(minutes: pd.DataFrame, cluster: str = "split_group", cov_type: str = "bias_reduced") -> dict[str, WaldTest]:
    """H3: one test per moderator, Holm-adjusted across the three."""
    raw = {moderator: moderation_test(minutes, moderator, cluster, cov_type) for moderator in MODERATORS}
    adjusted = multipletests([test.p_value for test in raw.values()], method="holm")[1]
    return {moderator: _with_holm(test, float(p)) for (moderator, test), p in zip(raw.items(), adjusted, strict=True)}


def _with_holm(test: WaldTest, holm: float) -> WaldTest:
    return WaldTest(test.statistic, test.degrees_of_freedom, test.p_value, holm, test.estimates)
