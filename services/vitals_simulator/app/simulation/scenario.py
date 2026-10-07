import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import replace

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.simulation.bedside import BedsideReading
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading

NORMAL_SCENARIO = "normal"
DETERIORATION_SCENARIO = "deterioration_proxy"
SCENARIOS = (NORMAL_SCENARIO, DETERIORATION_SCENARIO)

FEATURE_WINDOW_SECONDS = 15 * 60
OUTCOME_WINDOW_SECONDS = 15 * 60
# A run shorter than this produces no outcome label.
LABEL_WINDOW_SECONDS = FEATURE_WINDOW_SECONDS + OUTCOME_WINDOW_SECONDS


def choose_patient_scenarios(
    patient_ids: list[str], seed: str | int | None = None, prior_counts: Mapping[str, Mapping[str, int]] | None = None
) -> dict[str, str]:
    """Assign each patient a scenario.

    With prior_counts (each patient's earlier labelled runs per scenario), a patient gets the scenario it has had less
    often, so any two labelled runs give every patient both outcome classes, whichever patients the model tests on.
    Ties, and runs without prior_counts, use a stable hash of seed and patient when seeded, otherwise a random choice.
    The hash gives the same assignment for the same seed on every Python version and host.
    """
    scenarios = {}
    for patient_id in patient_ids:
        counts = (prior_counts or {}).get(patient_id, {})
        normal_runs, deterioration_runs = counts.get(NORMAL_SCENARIO, 0), counts.get(DETERIORATION_SCENARIO, 0)
        if normal_runs != deterioration_runs:
            scenarios[patient_id] = NORMAL_SCENARIO if normal_runs < deterioration_runs else DETERIORATION_SCENARIO
        elif seed is None:
            scenarios[patient_id] = secrets.choice(SCENARIOS)
        else:
            scenarios[patient_id] = SCENARIOS[_seeded_index(seed, patient_id)]
    return scenarios


def _seeded_index(seed: str | int, patient_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{patient_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % len(SCENARIOS)


def is_outcome_window(elapsed_seconds: float) -> bool:
    return FEATURE_WINDOW_SECONDS <= elapsed_seconds < FEATURE_WINDOW_SECONDS + OUTCOME_WINDOW_SECONDS


def apply_vital_scenario(reading: VitalReading, scenario: str, elapsed_seconds: float) -> VitalReading:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported simulation scenario: {scenario}")
    if not is_outcome_window(elapsed_seconds):
        return reading
    if scenario == DETERIORATION_SCENARIO:
        return replace(reading, heart_rate=135.0, respiratory_rate=28.0, spo2=89.0)
    return replace(
        reading,
        heart_rate=_clamp(reading.heart_rate, 50.0, 100.0),
        respiratory_rate=_clamp(reading.respiratory_rate, 12.0, 20.0),
        spo2=_clamp(reading.spo2, 95.0, 100.0),
    )


def apply_blood_pressure_scenario(reading: BloodPressureReading, scenario: str, elapsed_seconds: float) -> BloodPressureReading:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported simulation scenario: {scenario}")
    if not is_outcome_window(elapsed_seconds):
        return reading
    if scenario == DETERIORATION_SCENARIO:
        return replace(reading, systolic=85.0, diastolic=55.0)
    return replace(reading, systolic=_clamp_required(reading.systolic, 105.0, 130.0), diastolic=_clamp_required(reading.diastolic, 60.0, 85.0))


# Outcome-window bedside values of a deterioration encounter: fever, supplemental oxygen and new confusion (ACVPU C).
DETERIORATION_TEMPERATURE = 38.6
DETERIORATION_INHALED_OXYGEN = 28.0
DETERIORATION_CONSCIOUSNESS = 1


def apply_bedside_scenario(reading: BedsideReading, scenario: str, elapsed_seconds: float) -> BedsideReading:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported simulation scenario: {scenario}")
    if scenario != DETERIORATION_SCENARIO or not is_outcome_window(elapsed_seconds):
        return reading
    return replace(
        reading,
        temperature=DETERIORATION_TEMPERATURE,
        inhaled_oxygen_concentration=DETERIORATION_INHALED_OXYGEN,
        consciousness_level=DETERIORATION_CONSCIOUSNESS,
    )


def _clamp(value: float | None, minimum: float, maximum: float) -> float | None:
    if value is None:
        return None
    return min(max(value, minimum), maximum)


def _clamp_required(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)
