"""The plan's decision rules (plans/analysis-plan.md, Tests and Decision Rules), applied to computed statistics.

Failure modes (written before the code):

1. H1 is called supported on the joint test alone while the GEE model's AUC interval still contains 0.5: both are needed.
2. H2 counts a model whose AUC is significantly lower than NEWS2's: only a higher AUC supports H2.
3. H2 or H3 uses the raw p-value instead of the Holm-adjusted one.
4. A p-value of exactly 0.05 counts as significant: the rule is p < 0.05.
"""

from __future__ import annotations

from jobs.analysis.models import JointTest
from jobs.analysis.run import Comparison, decide
from testkit import expect


def joint(p: float, holm: float | None = None) -> JointTest:
    return JointTest(statistic=1.0, degrees_of_freedom=1, p_value=p, holm_p_value=holm)


def test_h1_needs_the_joint_test_and_an_interval_above_one_half() -> None:
    expect.equal(decide(joint(0.001), (0.48, 0.70), {}, {}).h1, False)
    expect.equal(decide(joint(0.20), (0.60, 0.80), {}, {}).h1, False)
    expect.equal(decide(joint(0.001), (0.60, 0.80), {}, {}).h1, True)


def test_h2_counts_only_models_above_news2_after_holm() -> None:
    comparisons = {
        "gradient_boosting": Comparison(difference=0.10, p_value=0.001, holm_p_value=0.003),
        "naive_logistic": Comparison(difference=-0.10, p_value=0.001, holm_p_value=0.003),
        "gee_logistic": Comparison(difference=0.05, p_value=0.02, holm_p_value=0.06),
    }

    decisions = decide(joint(0.5), (0.4, 0.6), comparisons, {})

    expect.equal((decisions.h2, decisions.h2_models), (True, ("gradient_boosting",)))
    expect.equal(decide(joint(0.5), (0.4, 0.6), {"gee_logistic": comparisons["gee_logistic"]}, {}).h2, False)


def test_h3_uses_holm_and_a_strict_threshold() -> None:
    moderation = {"age_65_plus": joint(0.01, 0.03), "diagnosis_group": joint(0.02, 0.05), "specialty_group": joint(0.04, 0.08)}

    decisions = decide(joint(0.5), (0.4, 0.6), {}, moderation)

    expect.equal((decisions.h3, decisions.h3_moderators), (True, ("age_65_plus",)))
    expect.equal(decide(joint(0.05), (0.6, 0.8), {}, {"age_65_plus": joint(0.01, 0.05)}).h3, False)
    expect.equal(decide(joint(0.05), (0.6, 0.8), {}, {}).h1, False)
