"""AUC, DeLong's test for two correlated ROC curves and the split-group bootstrap of the analysis.

The AUC is the Mann-Whitney probability that a positive scores above a negative, ties counting half. DeLong's test
uses the structural components of DeLong, DeLong and Clarke-Pearson (1988) computed from midranks (Sun and Xu 2014).
The bootstrap resamples whole split groups, so encounters that share a waveform record stay together; it holds the
scores fixed and does not refit models. See plans/analysis-plan.md (local).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


class RocError(ValueError):
    """An AUC or test cannot be computed from these labels and scores."""


@dataclass(frozen=True)
class DeLong:
    auc_a: float
    auc_b: float
    difference: float
    standard_error: float
    z: float
    p_value: float


@dataclass(frozen=True)
class Bootstrap:
    intervals: dict[str, tuple[float, float]]
    difference_intervals: dict[str, tuple[float, float]]
    resamples: int
    skipped: int


def _midranks(values: np.ndarray) -> np.ndarray:
    """1-based ranks with tied values sharing their average rank."""
    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    ranks = np.empty(len(values))
    start = 0
    while start < len(values):
        end = start
        while end + 1 < len(values) and ordered[end + 1] == ordered[start]:
            end += 1
        ranks[order[start : end + 1]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def _classes(labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    labels = np.asarray(labels)
    positives, negatives = labels == 1, labels == 0
    if not positives.any() or not negatives.any():
        raise RocError("an AUC needs labels of both classes")
    return positives, negatives


def _components(labels: np.ndarray, scores: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """The AUC and the structural components V10 (per positive) and V01 (per negative)."""
    positives, negatives = _classes(labels)
    scores = np.asarray(scores, dtype=float)
    if not np.isfinite(scores).all():
        raise RocError(f"{int((~np.isfinite(scores)).sum())} scores are missing or not finite; the model did not fit")
    m, n = int(positives.sum()), int(negatives.sum())
    overall = _midranks(scores)
    within_positives = _midranks(scores[positives])
    within_negatives = _midranks(scores[negatives])
    v10 = (overall[positives] - within_positives) / n
    v01 = 1.0 - (overall[negatives] - within_negatives) / m
    return float(v10.mean()), v10, v01


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    return _components(labels, scores)[0]


def delong(labels: np.ndarray, scores_a: np.ndarray, scores_b: np.ndarray) -> DeLong:
    """DeLong's two-sided test of AUC(a) = AUC(b) on the same encounters."""
    auc_a, v10_a, v01_a = _components(labels, scores_a)
    auc_b, v10_b, v01_b = _components(labels, scores_b)
    covariance = np.cov(np.vstack([v10_a, v10_b])) / len(v10_a) + np.cov(np.vstack([v01_a, v01_b])) / len(v01_a)
    variance = float(covariance[0, 0] + covariance[1, 1] - 2 * covariance[0, 1])
    difference = auc_a - auc_b
    if variance <= 1e-15:
        return DeLong(auc_a, auc_b, 0.0 if abs(difference) < 1e-15 else difference, 0.0, 0.0, 1.0 if abs(difference) < 1e-15 else 0.0)
    z = difference / math.sqrt(variance)
    return DeLong(auc_a, auc_b, difference, math.sqrt(variance), z, math.erfc(abs(z) / math.sqrt(2)))


def bootstrap(labels: np.ndarray, scores: dict[str, np.ndarray], groups: np.ndarray, reference: str, resamples: int, seed: int) -> Bootstrap:
    """Percentile 95% intervals of each AUC and of each AUC minus the reference's, resampling whole groups."""
    labels, groups = np.asarray(labels), np.asarray(groups)
    unique = np.unique(groups)
    rows = [np.flatnonzero(groups == group) for group in unique]
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {name: [] for name in scores}
    skipped = 0
    for _ in range(resamples):
        chosen = np.concatenate([rows[index] for index in rng.integers(0, len(unique), size=len(unique))])
        if len(np.unique(labels[chosen])) < 2:
            skipped += 1
            continue
        for name, values in scores.items():
            draws[name].append(auc(labels[chosen], np.asarray(values)[chosen]))
    if not draws[reference]:
        raise RocError("every bootstrap resample held one class")

    def interval(values: list[float] | np.ndarray) -> tuple[float, float]:
        low, high = np.percentile(values, [2.5, 97.5])
        return float(low), float(high)

    reference_draws = np.array(draws[reference])
    return Bootstrap(
        intervals={name: interval(values) for name, values in draws.items()},
        difference_intervals={name: interval(np.array(values) - reference_draws) for name, values in draws.items() if name != reference},
        resamples=resamples,
        skipped=skipped,
    )
