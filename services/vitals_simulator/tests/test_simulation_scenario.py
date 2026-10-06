from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.simulation.scenario import (
    DETERIORATION_SCENARIO,
    FEATURE_WINDOW_SECONDS,
    NORMAL_SCENARIO,
    apply_blood_pressure_scenario,
    apply_vital_scenario,
    choose_patient_scenarios,
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


def test_deterioration_scenario_crosses_proxy_thresholds_in_outcome_window():
    reading = VitalReading("bidmc01n", 0, 82.0, 18.0, 97.0)
    blood_pressure = BloodPressureReading("patient-1", "bp-1", 120.0, 75.0)

    changed = apply_vital_scenario(reading, DETERIORATION_SCENARIO, FEATURE_WINDOW_SECONDS)
    changed_bp = apply_blood_pressure_scenario(blood_pressure, DETERIORATION_SCENARIO, FEATURE_WINDOW_SECONDS)

    expect.equal((changed.heart_rate, changed.respiratory_rate, changed.spo2), (135.0, 28.0, 89.0))
    expect.equal((changed_bp.systolic, changed_bp.diastolic), (85.0, 55.0))


def test_normal_scenario_clamps_extreme_values_in_outcome_window():
    reading = VitalReading("bidmc01n", 0, 150.0, 30.0, 88.0)
    blood_pressure = BloodPressureReading("patient-1", "bp-1", 80.0, 45.0)

    changed = apply_vital_scenario(reading, NORMAL_SCENARIO, FEATURE_WINDOW_SECONDS)
    changed_bp = apply_blood_pressure_scenario(blood_pressure, NORMAL_SCENARIO, FEATURE_WINDOW_SECONDS)

    expect.equal((changed.heart_rate, changed.respiratory_rate, changed.spo2), (100.0, 20.0, 95.0))
    expect.equal((changed_bp.systolic, changed_bp.diastolic), (105.0, 60.0))


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
