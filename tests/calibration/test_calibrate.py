"""Scaling the planted signal for calibration.

Failure modes (written before the code):

1. Scaling changes the share of deterioration encounters with a precursor: only effect sizes and the oxygen and
   confusion probabilities scale; precursor_probability, the ramp and the age multiplier stay.
2. A probability scaled above 1 breaks the draw: probabilities are capped at 1.
3. Scaling the null control plants something: zero effects and probabilities stay zero.
4. RQ3 needs the planted age effect to be detectable: the interaction of age 65 and over with deterioration on the
   heart-rate rise is estimated with a patient-clustered bootstrap CI that excludes 0 when the effect is planted and
   includes it when it is not, and the same rows always give the same CI.
"""

import numpy as np

from jobs.calibration.calibrate import rq3_interaction, scaled_signal
from services.vitals_simulator.app.simulation.precursor import load_planted_signal
from testkit import expect


def test_only_effect_sizes_and_event_probabilities_scale() -> None:
    base = load_planted_signal("study")
    scaled = scaled_signal(base, trend_scale=2.0, event_scale=10.0)

    expect.equal(scaled["effects"]["heart_rate"], {"mean": base["effects"]["heart_rate"]["mean"] * 2, "sd": base["effects"]["heart_rate"]["sd"] * 2})
    expected = tuple(min(1.0, round(base[event]["probability"] * 10.0, 6)) for event in ("supplemental_oxygen", "new_confusion"))
    expect.equal((scaled["supplemental_oxygen"]["probability"], scaled["new_confusion"]["probability"]), expected)
    expect.equal(scaled_signal(base, 1.0, 100.0)["supplemental_oxygen"]["probability"], 1.0)
    for key in ("precursor_probability", "ramp_start_seconds", "ramp_end_seconds", "age_65_plus_heart_rate_multiplier"):
        expect.equal(scaled[key], base[key])


def test_scaling_the_null_control_plants_nothing() -> None:
    null = scaled_signal(load_planted_signal("null_control"), trend_scale=3.0, event_scale=3.0)

    expect.equal({spec["mean"] for spec in null["effects"].values()}, {0.0})
    expect.equal((null["supplemental_oxygen"]["probability"], null["new_confusion"]["probability"]), (0.0, 0.0))


def rows(interaction: float, seed: int) -> list[dict]:
    """Synthetic encounters: heart-rate rise = 6 for deterioration, plus the interaction for older patients, plus noise."""
    rng = np.random.default_rng(seed)
    built = []
    for patient in range(100):
        older = patient < 30
        for run in range(6):
            label = run % 2
            rise = 6.0 * label + interaction * label * older + rng.normal(0.0, 3.0)
            built.append({"patient": f"p{patient}", "age_65_plus": older, "label": label, "hr_rise": rise})
    return built


def test_the_age_interaction_is_found_when_planted_and_not_otherwise() -> None:
    planted = rq3_interaction(rows(-3.0, 1))
    absent = rq3_interaction(rows(0.0, 2))

    if not (planted["upper"] < 0 and planted["lower"] < planted["estimate"] < planted["upper"]):
        expect.fail(f"expected: a negative interaction with a CI below 0, got {planted}")
    if not absent["lower"] <= 0 <= absent["upper"]:
        expect.fail(f"expected: a CI that includes 0 without a planted interaction, got {absent}")
    expect.equal(rq3_interaction(rows(-3.0, 1)), planted)
