"""AUC, DeLong's test and the split-group bootstrap of the analysis (plans/analysis-plan.md, H1 and H2).

Failure modes (written before the code):

1. Tied scores are counted as wins or losses instead of half: the AUC must equal the Mann-Whitney definition.
2. DeLong's variance is wrong (a sign or index slip in the structural components): it must equal a slow,
   independent computation of the same components.
3. Two identical score vectors divide by a zero variance: the difference is 0 and the p-value 1.
4. Labels of one class have no AUC: stop and say so instead of returning a number.
5. The bootstrap resamples encounters instead of whole split groups, so its intervals are too narrow: copying every
   group's rows must leave the interval unchanged.
6. A resample draws only one class: it is skipped and counted, not fatal, and the interval uses the rest.
7. A rerun gives a different interval: the same seed gives the same result.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from jobs.analysis import roc
from testkit import expect


def sample(seed: int = 1, n: int = 80) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    labels = np.array([0, 1] * (n // 2))
    a = labels * 1.0 + rng.normal(size=n)
    b = 0.5 * a + rng.normal(size=n)
    return labels, a, b


def slow_delong_covariance(labels: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The 2x2 covariance of the two AUCs from DeLong's structural components, computed pairwise."""

    def kernel(x: float, y: float) -> float:
        return 1.0 if x > y else 0.5 if x == y else 0.0

    positives, negatives = np.flatnonzero(labels == 1), np.flatnonzero(labels == 0)
    v10 = np.array([[np.mean([kernel(s[i], s[j]) for j in negatives]) for i in positives] for s in (a, b)])
    v01 = np.array([[np.mean([kernel(s[i], s[j]) for i in positives]) for j in negatives] for s in (a, b)])
    return np.cov(v10) / len(positives) + np.cov(v01) / len(negatives)


def test_tied_scores_count_half() -> None:
    labels = np.array([0, 0, 1, 1, 0, 1])
    scores = np.array([1.0, 2.0, 2.0, 3.0, 2.0, 2.0])

    expect.equal(round(roc.auc(labels, scores), 12), round(roc_auc_score(labels, scores), 12))


def test_delong_matches_the_pairwise_structural_components() -> None:
    labels, a, b = sample()
    covariance = slow_delong_covariance(labels, a, b)
    variance = covariance[0, 0] + covariance[1, 1] - 2 * covariance[0, 1]

    result = roc.delong(labels, a, b)

    expect.equal(round(result.auc_a, 12), round(roc_auc_score(labels, a), 12))
    expect.equal(round(result.auc_b, 12), round(roc_auc_score(labels, b), 12))
    expect.equal(round(result.standard_error**2, 12), round(variance, 12))


def test_identical_scores_have_no_difference() -> None:
    labels, a, _ = sample()

    result = roc.delong(labels, a, a.copy())

    expect.equal((result.difference, result.p_value), (0.0, 1.0))


def test_one_class_has_no_auc() -> None:
    with pytest.raises(roc.RocError, match="both classes"):
        roc.auc(np.array([1, 1, 1]), np.array([0.1, 0.2, 0.3]))


def test_the_bootstrap_resamples_whole_groups() -> None:
    labels, a, b = sample(n=60)
    groups = np.repeat(np.arange(12), 5)
    scores = {"model": a, "news2": b}

    once = roc.bootstrap(labels, scores, groups, reference="news2", resamples=300, seed=7)
    doubled = roc.bootstrap(np.tile(labels, 2), {name: np.tile(values, 2) for name, values in scores.items()}, np.tile(groups, 2), "news2", 300, 7)

    for name in ("model", "news2"):
        if not np.allclose(once.intervals[name], doubled.intervals[name], atol=0.03):
            expect.fail(f"expected: copying each group's rows leaves the {name} interval unchanged, got {once.intervals[name]} and {doubled.intervals[name]}")
    expect.is_in("model", once.difference_intervals)


def test_one_class_resamples_are_skipped_and_counted() -> None:
    labels = np.array([0, 0, 0, 1, 1, 1])
    scores = {"model": np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9]), "news2": np.array([0.2, 0.1, 0.4, 0.6, 0.9, 0.3])}
    groups = np.array([0, 0, 0, 1, 1, 1])  # each group holds one class

    result = roc.bootstrap(labels, scores, groups, "news2", resamples=200, seed=3)

    if not 0 < result.skipped < 200:
        expect.fail(f"expected: some one-class resamples skipped and counted, got {result.skipped}")


def test_the_same_seed_gives_the_same_intervals() -> None:
    labels, a, b = sample(n=60)
    groups = np.repeat(np.arange(12), 5)

    first = roc.bootstrap(labels, {"model": a, "news2": b}, groups, "news2", 200, 11)
    second = roc.bootstrap(labels, {"model": a, "news2": b}, groups, "news2", 200, 11)

    expect.equal(first, second)
