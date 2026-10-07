"""Bedside measures the simulator adds to each observation set: temperature, inhaled oxygen and ACVPU.

Failure modes (written before the code):

1. Synthea records temperature only at illness visits, so its values are not a resting baseline: every patient gets a
   seeded baseline near 36.8 degrees Celsius instead.
2. The baseline must not change between runs or environments: it is seeded by the Synthea patient ID alone.
3. A baseline far from normal would look like fever or hypothermia before any scenario: it stays within 36.3 to 37.3.
4. The cadence is asked twice within one interval: each observation set is emitted once, never twice.
5. The same patient and run give the same values; another run gives different noise.
6. A deterioration encounter's outcome window shows fever, supplemental oxygen and new confusion; a normal one stays
   afebrile, on room air and alert. Before the outcome window both scenarios look the same (no planted signal yet).
"""

from services.vitals_simulator.app.simulation.bedside import BASELINE_RANGE, ROOM_AIR_PERCENT, BedsideCadence, BedsideReading, baseline_temperature
from services.vitals_simulator.app.simulation.scenario import DETERIORATION_SCENARIO, NORMAL_SCENARIO, apply_bedside_scenario
from testkit import expect


def test_every_patient_gets_a_stable_seeded_baseline_in_the_normal_range() -> None:
    baselines = [baseline_temperature(f"synthea-{index}") for index in range(200)]

    expect.equal(baseline_temperature("synthea-2"), baselines[2])
    if not all(BASELINE_RANGE[0] <= value <= BASELINE_RANGE[1] for value in baselines):
        expect.fail(f"expected: every baseline inside {BASELINE_RANGE}")
    if not 36.7 <= sum(baselines) / len(baselines) <= 36.9 or len(set(baselines)) < 5:
        expect.fail("expected: baselines vary around 36.8")


def test_each_observation_set_is_emitted_once_per_interval() -> None:
    cadence = BedsideCadence(baseline_temperature=36.8, seed_key="seed:patient:run-1", interval_seconds=300)

    emitted = [elapsed for elapsed in range(0, 901) if cadence.get_reading(elapsed) is not None]

    expect.equal(emitted, [0, 300, 600, 900])


def test_values_are_seeded_by_patient_and_run() -> None:
    def temperatures(seed_key: str) -> list[float | None]:
        cadence = BedsideCadence(baseline_temperature=36.8, seed_key=seed_key, interval_seconds=300)
        return [reading.temperature for elapsed in range(0, 1800, 300) if (reading := cadence.get_reading(elapsed))]

    expect.equal(temperatures("seed:patient:run-1"), temperatures("seed:patient:run-1"))
    if temperatures("seed:patient:run-1") == temperatures("seed:patient:run-2"):
        expect.fail("expected: another run gives different temperature noise")


def test_the_outcome_window_follows_the_scenario_and_the_feature_window_does_not() -> None:
    baseline = BedsideReading(temperature=36.9, inhaled_oxygen_concentration=ROOM_AIR_PERCENT, consciousness_level=0)

    deteriorating = apply_bedside_scenario(baseline, DETERIORATION_SCENARIO, 1200)
    normal = apply_bedside_scenario(baseline, NORMAL_SCENARIO, 1200)

    temperature, oxygen, consciousness = deteriorating.temperature, deteriorating.inhaled_oxygen_concentration, deteriorating.consciousness_level
    if temperature is None or oxygen is None or consciousness is None or not (temperature >= 38.1 and oxygen > ROOM_AIR_PERCENT and consciousness >= 1):
        expect.fail(f"expected: fever, supplemental oxygen and new confusion, got {deteriorating}")
    expect.equal(normal, baseline)
    expect.equal(apply_bedside_scenario(baseline, DETERIORATION_SCENARIO, 600), baseline)
