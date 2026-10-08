"""The planted precursor: a seeded early-warning trend in the feature window of deterioration encounters.

This is the known truth of the simulation study (config/planted_signal.json). Failure modes (written before the code):

1. A normal encounter gets a precursor, or any encounter does in the null control: the study would have no clean
   negative class or no null. Normal encounters and every null-control encounter get none.
2. Every deterioration encounter gets a precursor: the model would separate the classes perfectly. A seeded share of
   them is silent.
3. The precursor leaks into the outcome window or starts before its ramp: it rises only between ramp start and the
   feature-window end, and the outcome window keeps the scenario's values.
4. Patients aged 65 and over must show a blunted heart-rate response (the RQ3 effect): their heart-rate drift is the
   configured fraction of the others'; the other vitals are unchanged.
5. A rerun must repeat the study: the same seed, patient and run give the same precursor; another run differs.
6. A drift pushes a value outside the processor's ranges (SpO2 above 100): values are clamped to the catalog ranges.
7. A waveform dropout the processor rejects (SpO2 0, respiratory rate 0) drifts during the ramp: it must stay outside
   the ranges, so the processor still rejects it. Clamping it to the lowest valid value would add readings that only
   deterioration encounters have, a marker of the label.
"""

from dataclasses import replace

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.simulation.bedside import ROOM_AIR_PERCENT, BedsideReading
from services.vitals_simulator.app.simulation.precursor import (
    NO_PRECURSOR,
    apply_precursor_to_bedside,
    apply_precursor_to_vitals,
    load_planted_signal,
    sample_precursor,
)
from services.vitals_simulator.app.simulation.scenario import DETERIORATION_SCENARIO, FEATURE_WINDOW_SECONDS, NORMAL_SCENARIO
from testkit import expect

STUDY = load_planted_signal("study")
NULL = load_planted_signal("null_control")


def precursors(signal, scenario: str, age_65_plus: bool = False, count: int = 400) -> list:
    return [sample_precursor(signal, scenario, "4817263", f"patient-{index}", "batch-4817263-1", age_65_plus) for index in range(count)]


def test_only_study_deterioration_encounters_get_a_precursor() -> None:
    expect.equal(set(precursors(STUDY, NORMAL_SCENARIO)), {NO_PRECURSOR})
    expect.equal(set(precursors(NULL, DETERIORATION_SCENARIO)), {NO_PRECURSOR})


def test_a_seeded_share_of_deterioration_encounters_is_silent() -> None:
    planted = [precursor for precursor in precursors(STUDY, DETERIORATION_SCENARIO) if precursor != NO_PRECURSOR]
    share = len(planted) / 400
    expected = STUDY["precursor_probability"]

    if not expected - 0.06 <= share <= expected + 0.06:
        expect.fail(f"expected: about {expected:.0%} of deterioration encounters with a precursor, got {share:.0%}")
    if len({precursor.heart_rate for precursor in planted}) < 50:
        expect.fail("expected: precursor sizes vary between encounters")


def test_the_precursor_ramps_inside_the_feature_window_only() -> None:
    precursor = next(precursor for precursor in precursors(STUDY, DETERIORATION_SCENARIO) if precursor.heart_rate > 5)
    reading = VitalReading("bidmc01n", 0, 80.0, 16.0, 97.0)

    before = apply_precursor_to_vitals(reading, precursor, STUDY["ramp_start_seconds"] - 1)
    full = apply_precursor_to_vitals(reading, precursor, FEATURE_WINDOW_SECONDS - 1)
    outcome = apply_precursor_to_vitals(reading, precursor, FEATURE_WINDOW_SECONDS)

    expect.equal(before, reading)
    if abs(full.heart_rate - (80.0 + precursor.heart_rate)) > 0.2:
        expect.fail(f"expected: the full heart-rate drift by the feature-window end, got {full.heart_rate}")
    expect.equal(outcome, reading)


def test_patients_aged_65_and_over_get_a_blunted_heart_rate_drift() -> None:
    younger = sample_precursor(STUDY, DETERIORATION_SCENARIO, "4817263", "patient-7", "batch-4817263-1", age_65_plus=False)
    older = sample_precursor(STUDY, DETERIORATION_SCENARIO, "4817263", "patient-7", "batch-4817263-1", age_65_plus=True)

    expect.equal(round(older.heart_rate, 6), round(younger.heart_rate * STUDY["age_65_plus_heart_rate_multiplier"], 6))
    expect.equal(replace(older, heart_rate=0.0, age_65_plus=False), replace(younger, heart_rate=0.0))


def test_the_same_seed_patient_and_run_repeat_the_precursor() -> None:
    first = sample_precursor(STUDY, DETERIORATION_SCENARIO, "4817263", "patient-3", "batch-4817263-2", False)

    expect.equal(sample_precursor(STUDY, DETERIORATION_SCENARIO, "4817263", "patient-3", "batch-4817263-2", False), first)
    if sample_precursor(STUDY, DETERIORATION_SCENARIO, "4817263", "patient-3", "batch-4817263-5", False) == first:
        expect.fail("expected: another run gives another precursor")


def test_drifted_values_stay_inside_the_processor_ranges() -> None:
    precursor = replace(next(p for p in precursors(STUDY, DETERIORATION_SCENARIO) if p != NO_PRECURSOR), spo2=5.0, temperature=20.0)
    vitals = apply_precursor_to_vitals(VitalReading("bidmc01n", 0, 80.0, 16.0, 99.0), precursor, FEATURE_WINDOW_SECONDS - 1)
    bedside = apply_precursor_to_bedside(BedsideReading(37.0, ROOM_AIR_PERCENT, 0), precursor, FEATURE_WINDOW_SECONDS - 1)

    if vitals.spo2 is None or vitals.spo2 > 100 or bedside.temperature is None or bedside.temperature > 45:
        expect.fail(f"expected: values clamped to the catalog ranges, got {vitals} and {bedside}")


def test_a_dropout_the_processor_rejects_stays_rejected() -> None:
    precursor = next(p for p in precursors(STUDY, DETERIORATION_SCENARIO) if p != NO_PRECURSOR)
    dropout = VitalReading("bidmc19n", 0, 80.0, 0.0, 0.0)

    vitals = apply_precursor_to_vitals(dropout, precursor, FEATURE_WINDOW_SECONDS - 1)

    expect.equal((vitals.respiratory_rate, vitals.spo2), (0.0, 0.0))
