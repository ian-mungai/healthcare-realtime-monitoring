import random
from dataclasses import replace

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading

NORMAL_SCENARIO = "normal"
DETERIORATION_SCENARIO = "deterioration_proxy"
SCENARIOS = (NORMAL_SCENARIO, DETERIORATION_SCENARIO)

FEATURE_WINDOW_SECONDS = 15 * 60
OUTCOME_WINDOW_SECONDS = 15 * 60


def choose_patient_scenarios(patient_ids: list[str], seed: str | int | None = None) -> dict[str, str]:
    rng = random.Random(seed)
    return {patient_id: rng.choice(SCENARIOS) for patient_id in patient_ids}


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


def _clamp(value: float | None, minimum: float, maximum: float) -> float | None:
    if value is None:
        return None
    return min(max(value, minimum), maximum)


def _clamp_required(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)
