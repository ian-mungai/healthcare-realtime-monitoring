import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace

from services.vital_signs import REALTIME_VITAL_RANGES
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


# Outcome-window range of each deterioration vital (owner-approved Oct 8 2026). Every value stays past the limits of the
# label news2-repeated-extreme-proxy-v2: heart rate 131 or more, respiratory rate 25 or more, SpO2 91 or less and systolic
# pressure 90 or less. Temperature is fever, inhaled oxygen is supplemental and consciousness is C (1) or V (2).
DETERIORATION_RANGES: dict[str, tuple[float, float]] = {
    "heart_rate": (131.0, 150.0),
    "respiratory_rate": (25.0, 32.0),
    "spo2": (85.0, 91.0),
    "systolic_bp": (75.0, 90.0),
    "diastolic_bp": (45.0, 60.0),
    "temperature": (38.1, 39.5),
    "inhaled_oxygen_concentration": (24.0, 40.0),
    "consciousness_level": (1.0, 2.0),
}
# Largest change of one reading from its target, and the decimals it is recorded with. Inhaled oxygen and consciousness
# hold for the whole window: they are a device setting and a state, not a measurement with noise.
_READING_NOISE = {"heart_rate": 3.0, "respiratory_rate": 1.5, "spo2": 1.0, "systolic_bp": 3.0, "diastolic_bp": 3.0, "temperature": 0.2}
_DECIMALS = {"heart_rate": 1, "respiratory_rate": 1, "spo2": 1, "systolic_bp": 0, "diastolic_bp": 0, "temperature": 1, "inhaled_oxygen_concentration": 0}


@dataclass(frozen=True)
class DeteriorationTargets:
    """One deterioration encounter's outcome-window value per vital; seed_key also seeds the noise of each reading."""

    seed_key: str
    heart_rate: float
    respiratory_rate: float
    spo2: float
    systolic_bp: float
    diastolic_bp: float
    temperature: float
    inhaled_oxygen_concentration: float
    consciousness_level: int

    def reading(self, name: str, elapsed_seconds: float) -> float:
        """The target plus this reading's seeded noise, rounded as recorded and kept inside the approved range."""
        low, high = DETERIORATION_RANGES[name]
        noise = _READING_NOISE[name] * (2 * _unit(f"{self.seed_key}:{name}:{elapsed_seconds:.3f}") - 1)
        return min(max(round(getattr(self, name) + noise, _DECIMALS[name]), low), high)


def deterioration_targets(seed: str | int | None, patient_id: str, run_id: str) -> DeteriorationTargets:
    """The encounter's targets, drawn evenly from each range and seeded by the seed, the patient and the run."""
    seed_key = f"deterioration:{seed}:{patient_id}:{run_id}"
    drawn = {}
    for name in _DECIMALS:
        low, high = DETERIORATION_RANGES[name]
        drawn[name] = round(low + (high - low) * _unit(f"{seed_key}:{name}"), _DECIMALS[name])
    return DeteriorationTargets(seed_key=seed_key, consciousness_level=1 + int(_unit(f"{seed_key}:consciousness_level") >= 0.5), **drawn)


def _unit(key: str) -> float:
    """A number in [0, 1) from a stable hash, the same on every Python version and host."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") / 2**64


def _deterioration(scenario: str, elapsed_seconds: float, targets: DeteriorationTargets | None) -> DeteriorationTargets | None:
    """The targets to apply, or None when the reading keeps its value or follows the normal scenario."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported simulation scenario: {scenario}")
    if scenario != DETERIORATION_SCENARIO or not is_outcome_window(elapsed_seconds):
        return None
    if targets is None:
        raise ValueError("a deterioration outcome window needs the encounter's targets (deterioration_targets)")
    return targets


def apply_vital_scenario(reading: VitalReading, scenario: str, elapsed_seconds: float, targets: DeteriorationTargets | None = None) -> VitalReading:
    deterioration = _deterioration(scenario, elapsed_seconds, targets)
    if deterioration is not None:
        return replace(
            reading,
            heart_rate=deterioration.reading("heart_rate", elapsed_seconds),
            respiratory_rate=deterioration.reading("respiratory_rate", elapsed_seconds),
            spo2=deterioration.reading("spo2", elapsed_seconds),
        )
    if scenario == DETERIORATION_SCENARIO or not is_outcome_window(elapsed_seconds):
        return reading
    return replace(
        reading,
        heart_rate=_reflect("heart_rate", reading.heart_rate),
        respiratory_rate=_reflect("respiratory_rate", reading.respiratory_rate),
        spo2=_reflect("spo2", reading.spo2),
    )


def apply_blood_pressure_scenario(
    reading: BloodPressureReading, scenario: str, elapsed_seconds: float, targets: DeteriorationTargets | None = None
) -> BloodPressureReading:
    deterioration = _deterioration(scenario, elapsed_seconds, targets)
    if deterioration is not None:
        return replace(
            reading, systolic=deterioration.reading("systolic_bp", elapsed_seconds), diastolic=deterioration.reading("diastolic_bp", elapsed_seconds)
        )
    if scenario == DETERIORATION_SCENARIO or not is_outcome_window(elapsed_seconds):
        return reading
    return replace(reading, systolic=_reflect_required("systolic_bp", reading.systolic), diastolic=_reflect_required("diastolic_bp", reading.diastolic))


def apply_bedside_scenario(reading: BedsideReading, scenario: str, elapsed_seconds: float, targets: DeteriorationTargets | None = None) -> BedsideReading:
    """Fever, supplemental oxygen and new confusion in a deterioration outcome window; any other reading is unchanged."""
    deterioration = _deterioration(scenario, elapsed_seconds, targets)
    if deterioration is None:
        return reading
    return replace(
        reading,
        temperature=deterioration.reading("temperature", elapsed_seconds),
        inhaled_oxygen_concentration=deterioration.inhaled_oxygen_concentration,
        consciousness_level=deterioration.consciousness_level,
    )


# Outcome-window range of each normal vital. A source value outside it is reflected back inside, so a source that stays
# above or below the range keeps its variation instead of sitting on the limit.
NORMAL_RANGES: dict[str, tuple[float, float]] = {
    "heart_rate": (50.0, 100.0),
    "respiratory_rate": (12.0, 20.0),
    "spo2": (95.0, 100.0),
    "systolic_bp": (105.0, 130.0),
    "diastolic_bp": (60.0, 85.0),
}


def _reflect(name: str, value: float | None) -> float | None:
    """The value folded into the normal range at its limits; a value the stream processor rejects stays a dropout."""
    if value is None:
        return None
    accepted_low, accepted_high = REALTIME_VITAL_RANGES[name]
    if not accepted_low <= value <= accepted_high:
        return value
    low, high = NORMAL_RANGES[name]
    span = high - low
    offset = (value - low) % (2 * span)
    return round(low + (offset if offset <= span else 2 * span - offset), 1)


def _reflect_required(name: str, value: float) -> float:
    reflected = _reflect(name, value)
    return value if reflected is None else reflected
