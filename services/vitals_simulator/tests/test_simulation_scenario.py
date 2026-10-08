"""Scenario values in the outcome window.

Failure modes of the varied deterioration values (written before the code):

1. Every deterioration encounter shows the same values: each encounter draws its own target per vital in its range.
2. Noise pushes a reading back over a label limit (heart rate 131, respiratory rate 25, SpO2 91, systolic 90), which
   could change the label news2-repeated-extreme-proxy-v2: every reading is clamped inside its approved range.
3. Targets or noise differ between a rerun and the original: both are derived from the seed, patient, run and reading
   time, never from a random source, so the batch files repeat exactly.
4. A deterioration reading is built without its targets and silently falls back to fixed values: it raises instead.
5. The normal scenario or the feature window changes: neither reads the targets.

Failure modes of the normal outcome window (written before the code):

6. A source vital that stays outside its normal range is pinned to the limit, so the reading never moves (a flat line
   at heart rate 100): an out-of-range value is reflected back inside the range, which keeps the source's variation.
7. A reflected value leaves the normal range, which could cross a label limit: every value lands inside the range,
   however far outside the source value was.
8. A waveform dropout that the stream processor rejects becomes a valid reading only normal encounters have: values
   outside the processor's accepted range stay as they are.
9. A value already inside the normal range changes, or a rerun gives another value: values inside the range are kept and
   the reflection is plain arithmetic, so it repeats exactly.
"""

import pytest

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.simulation.bedside import BedsideReading
from services.vitals_simulator.app.simulation.scenario import (
    DETERIORATION_RANGES,
    DETERIORATION_SCENARIO,
    FEATURE_WINDOW_SECONDS,
    NORMAL_SCENARIO,
    OUTCOME_WINDOW_SECONDS,
    apply_bedside_scenario,
    apply_blood_pressure_scenario,
    apply_vital_scenario,
    choose_patient_scenarios,
    deterioration_targets,
)
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading
from testkit import expect


def test_scenario_selection_is_reproducible_with_seed():
    patient_ids = [str(patient_id) for patient_id in range(1000, 1010)]

    first = choose_patient_scenarios(patient_ids, seed="test-seed")
    second = choose_patient_scenarios(patient_ids, seed="test-seed")

    expect.equal(first, second)
    expect.equal(set(first), set(patient_ids))
    if not set(first.values()).issubset({NORMAL_SCENARIO, DETERIORATION_SCENARIO}):
        expect.fail("expected: set(first.values()).issubset({NORMAL_SCENARIO, DETERIORATION_SCENARIO})")


def test_scenario_does_not_change_feature_window_reading():
    reading = VitalReading("bidmc01n", 0, 82.0, 18.0, 97.0)

    expect.equal(apply_vital_scenario(reading, DETERIORATION_SCENARIO, FEATURE_WINDOW_SECONDS - 1), reading)


# The label news2-repeated-extreme-proxy-v2 limits: every deterioration value must stay past them.
LABEL_LIMITS = {"heart_rate": (131.0, None), "respiratory_rate": (25.0, None), "spo2": (None, 91.0), "systolic_bp": (None, 90.0)}


def outcome_window_values(seed_key: tuple[str, str, str]) -> dict[str, list[float]]:
    """Every outcome-window value of one deterioration encounter, read every 5 seconds as the simulator does."""
    targets = deterioration_targets(*seed_key)
    values: dict[str, list[float]] = {name: [] for name in DETERIORATION_RANGES}
    for elapsed in range(FEATURE_WINDOW_SECONDS, FEATURE_WINDOW_SECONDS + OUTCOME_WINDOW_SECONDS, 5):
        vitals = apply_vital_scenario(VitalReading("bidmc01n", 0, 82.0, 18.0, 97.0), DETERIORATION_SCENARIO, elapsed, targets)
        pressure = apply_blood_pressure_scenario(BloodPressureReading("patient-1", "bp-1", 120.0, 75.0), DETERIORATION_SCENARIO, elapsed, targets)
        bedside = apply_bedside_scenario(BedsideReading(36.9, 21.0, 0), DETERIORATION_SCENARIO, elapsed, targets)
        observed = {
            "heart_rate": vitals.heart_rate,
            "respiratory_rate": vitals.respiratory_rate,
            "spo2": vitals.spo2,
            "systolic_bp": pressure.systolic,
            "diastolic_bp": pressure.diastolic,
            "temperature": bedside.temperature,
            "inhaled_oxygen_concentration": bedside.inhaled_oxygen_concentration,
            "consciousness_level": bedside.consciousness_level,
        }
        for name, value in observed.items():
            if value is None:
                expect.fail(f"expected a {name} value at {elapsed} s")
            values[name].append(float(value))
    return values


def test_deterioration_values_stay_in_their_range_and_past_the_label_limits():
    for patient in range(20):
        values = outcome_window_values(("4817263", f"patient-{patient}", "run-1"))
        for name, (low, high) in DETERIORATION_RANGES.items():
            outside = [value for value in values[name] if not low <= value <= high]
            expect.equal(outside, [], f"{name} left its range {low} to {high}")
        for name, (at_least, at_most) in LABEL_LIMITS.items():
            crossed = [value for value in values[name] if (at_least is None or value >= at_least) and (at_most is None or value <= at_most)]
            expect.equal(len(crossed), len(values[name]), f"{name} went back over its label limit")


def test_each_deterioration_encounter_gets_its_own_seeded_targets():
    first = deterioration_targets("4817263", "patient-1", "run-1")

    expect.equal(deterioration_targets("4817263", "patient-1", "run-1"), first)
    others = {deterioration_targets("4817263", f"patient-{patient}", "run-1").heart_rate for patient in range(20)}
    if len(others) < 15:
        expect.fail(f"expected different heart-rate targets across encounters, got {sorted(others)}")
    if deterioration_targets("4817263", "patient-1", "run-2") == first:
        expect.fail("expected another run of the same patient to get other targets")
    consciousness = {deterioration_targets("4817263", f"patient-{patient}", "run-1").consciousness_level for patient in range(20)}
    expect.equal(consciousness, {1, 2})


def test_readings_vary_around_the_target_and_repeat_exactly():
    values = outcome_window_values(("4817263", "patient-1", "run-1"))

    expect.equal(outcome_window_values(("4817263", "patient-1", "run-1")), values)
    for name in ("heart_rate", "respiratory_rate", "spo2", "systolic_bp", "diastolic_bp", "temperature"):
        if len(set(values[name])) < 2:
            expect.fail(f"expected {name} to vary between readings, got {values[name][:5]}")


def test_a_deterioration_outcome_window_needs_targets():
    with pytest.raises(ValueError, match="targets"):
        apply_vital_scenario(VitalReading("bidmc01n", 0, 82.0, 18.0, 97.0), DETERIORATION_SCENARIO, FEATURE_WINDOW_SECONDS)


NORMAL_RANGES = {
    "heart_rate": (50.0, 100.0),
    "respiratory_rate": (12.0, 20.0),
    "spo2": (95.0, 100.0),
    "systolic_bp": (105.0, 130.0),
    "diastolic_bp": (60.0, 85.0),
}


def normal_values(heart_rate: float, respiratory_rate: float, spo2: float, systolic: float, diastolic: float) -> dict[str, float | None]:
    vitals = apply_vital_scenario(VitalReading("bidmc01n", 0, heart_rate, respiratory_rate, spo2), NORMAL_SCENARIO, FEATURE_WINDOW_SECONDS)
    pressure = apply_blood_pressure_scenario(BloodPressureReading("patient-1", "bp-1", systolic, diastolic), NORMAL_SCENARIO, FEATURE_WINDOW_SECONDS)
    return {
        "heart_rate": vitals.heart_rate,
        "respiratory_rate": vitals.respiratory_rate,
        "spo2": vitals.spo2,
        "systolic_bp": pressure.systolic,
        "diastolic_bp": pressure.diastolic,
    }


def test_normal_values_outside_the_range_are_reflected_inside_it():
    expect.equal(
        normal_values(107.4, 23.0, 92.5, 141.0, 52.0), {"heart_rate": 92.6, "respiratory_rate": 17.0, "spo2": 97.5, "systolic_bp": 119.0, "diastolic_bp": 68.0}
    )


def test_a_source_that_stays_above_the_range_still_varies():
    heart_rates = [normal_values(value, 16.0, 97.0, 120.0, 70.0)["heart_rate"] for value in (101.2, 103.8, 106.1, 104.0, 102.5)]

    expect.equal(len(set(heart_rates)), 5)


def test_every_normal_value_lands_inside_its_range():
    for heart_rate in (20.0, 49.0, 100.0, 151.3, 249.0):
        for name, value in normal_values(heart_rate, 79.0, 50.0, 299.0, 20.0).items():
            low, high = NORMAL_RANGES[name]
            if value is None or not low <= value <= high:
                expect.fail(f"{name} {value} is outside {low} to {high} for source heart rate {heart_rate}")


def test_values_inside_the_range_and_dropouts_are_kept():
    expect.equal(
        normal_values(72.3, 15.0, 98.0, 118.0, 74.0), {"heart_rate": 72.3, "respiratory_rate": 15.0, "spo2": 98.0, "systolic_bp": 118.0, "diastolic_bp": 74.0}
    )
    dropout = normal_values(0.0, 2.0, 30.0, 40.0, 10.0)
    expect.equal(dropout, {"heart_rate": 0.0, "respiratory_rate": 2.0, "spo2": 30.0, "systolic_bp": 40.0, "diastolic_bp": 10.0})


def test_scenario_selection_gives_each_patient_the_less_frequent_outcome():
    prior = {"1000": {NORMAL_SCENARIO: 2, DETERIORATION_SCENARIO: 1}, "1001": {NORMAL_SCENARIO: 0, DETERIORATION_SCENARIO: 1}}

    expect.equal(choose_patient_scenarios(["1000", "1001"], prior_counts=prior), {"1000": DETERIORATION_SCENARIO, "1001": NORMAL_SCENARIO})


def test_two_labelled_runs_give_every_patient_both_outcomes():
    patient_ids = [str(patient_id) for patient_id in range(1000, 1010)]
    prior: dict[str, dict[str, int]] = {patient_id: {} for patient_id in patient_ids}
    seen: dict[str, set[str]] = {patient_id: set() for patient_id in patient_ids}

    for _run in range(2):
        for patient_id, scenario in choose_patient_scenarios(patient_ids, prior_counts=prior).items():
            seen[patient_id].add(scenario)
            prior[patient_id][scenario] = prior[patient_id].get(scenario, 0) + 1

    expect.equal(seen, {patient_id: {NORMAL_SCENARIO, DETERIORATION_SCENARIO} for patient_id in patient_ids})
