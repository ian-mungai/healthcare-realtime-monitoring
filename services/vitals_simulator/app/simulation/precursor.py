"""The planted precursor: the known early-warning trend in the feature window of deterioration encounters.

The simulation study plants it so that models can be scored against a known truth (config/planted_signal.json). Each
deterioration encounter draws its own effect sizes, seeded by the seed, the patient and the run; a configured share
gets none, so the classes overlap. Normal encounters, and every encounter of the null control, get none. The drift
ramps in linearly from ramp_start_seconds to the feature-window end and never touches the outcome window, whose fixed
scenario values define the label. Patients aged 65 and over get a blunted heart-rate drift.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from services.vital_signs import REALTIME_VITAL_RANGES
from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.simulation.bedside import BedsideReading
from services.vitals_simulator.app.simulation.scenario import DETERIORATION_SCENARIO, FEATURE_WINDOW_SECONDS, SCENARIOS
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading

SIGNAL_MODES = ("study", "null_control")
CONFUSED = 1
_CANDIDATES = (Path(__file__).resolve().parents[4] / "config" / "planted_signal.json", Path.cwd() / "config" / "planted_signal.json")


@dataclass(frozen=True)
class Precursor:
    """Offsets reached at the feature-window end, plus the times supplemental oxygen and confusion begin."""

    heart_rate: float = 0.0
    respiratory_rate: float = 0.0
    spo2: float = 0.0
    systolic_bp: float = 0.0
    temperature: float = 0.0
    oxygen_from_seconds: float | None = None
    inhaled_oxygen_concentration: float | None = None
    confusion_from_seconds: float | None = None
    age_65_plus: bool = False
    ramp_start_seconds: float = 0.0
    ramp_end_seconds: float = FEATURE_WINDOW_SECONDS


NO_PRECURSOR = Precursor()


def load_planted_signal(mode: str) -> dict[str, Any]:
    if mode not in SIGNAL_MODES:
        raise ValueError(f"planted signal mode must be one of {', '.join(SIGNAL_MODES)}")
    for candidate in _CANDIDATES:
        if candidate.is_file():
            signal = json.loads(candidate.read_text(encoding="utf-8"))["signals"][mode]
            return {**signal, "version": json.loads(candidate.read_text(encoding="utf-8"))["version"], "mode": mode}
    raise RuntimeError("config/planted_signal.json is not packaged with this runtime")


def sample_precursor(signal: dict[str, Any], scenario: str, seed: str | int | None, patient_id: str, run_id: str, age_65_plus: bool) -> Precursor:
    """The encounter's precursor; the draws do not depend on age, so age changes only the heart-rate multiplier."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported simulation scenario: {scenario}")
    digest = hashlib.sha256(f"precursor:{seed}:{patient_id}:{run_id}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    planted = rng.random() < signal["precursor_probability"]
    effects = {name: float(rng.normal(spec["mean"], spec["sd"])) if spec["sd"] else float(spec["mean"]) for name, spec in signal["effects"].items()}
    oxygen, confusion = signal["supplemental_oxygen"], signal["new_confusion"]
    oxygen_on, oxygen_start = rng.random() < oxygen["probability"], float(rng.uniform(*oxygen["start_seconds"]))
    confused, confusion_start = rng.random() < confusion["probability"], float(rng.uniform(*confusion["start_seconds"]))
    if scenario != DETERIORATION_SCENARIO or not planted:
        return NO_PRECURSOR
    multiplier = signal["age_65_plus_heart_rate_multiplier"] if age_65_plus else 1.0
    return Precursor(
        heart_rate=effects["heart_rate"] * multiplier,
        respiratory_rate=effects["respiratory_rate"],
        spo2=effects["spo2"],
        systolic_bp=effects["systolic_bp"],
        temperature=effects["temperature"],
        oxygen_from_seconds=oxygen_start if oxygen_on else None,
        inhaled_oxygen_concentration=float(oxygen["concentration"]) if oxygen_on else None,
        confusion_from_seconds=confusion_start if confused else None,
        age_65_plus=age_65_plus,
        ramp_start_seconds=float(signal["ramp_start_seconds"]),
        ramp_end_seconds=float(signal["ramp_end_seconds"]),
    )


def is_65_plus(birth_date: str, at: datetime) -> bool:
    """Whether the patient is aged 65 or over on the day the encounter starts."""
    born = date.fromisoformat(birth_date)
    day = at.date()
    return (day.year - born.year - ((day.month, day.day) < (born.month, born.day))) >= 65


def ramp(precursor: Precursor, elapsed_seconds: float) -> float:
    """The share of the drift reached at this time: 0 before the ramp and in the outcome window, 1 at its end."""
    if precursor == NO_PRECURSOR or elapsed_seconds < precursor.ramp_start_seconds or elapsed_seconds >= FEATURE_WINDOW_SECONDS:
        return 0.0
    return min(1.0, (elapsed_seconds - precursor.ramp_start_seconds) / (precursor.ramp_end_seconds - precursor.ramp_start_seconds))


def _shift(field: str, value: float | None, offset: float) -> float | None:
    """The drifted value, kept in the processor's range; a value already outside it (a dropout) stays as it is."""
    if value is None or not offset:
        return value
    minimum, maximum = REALTIME_VITAL_RANGES[field]
    if not minimum <= value <= maximum:
        # The processor rejects it either way; clamping would turn a dropout into a valid reading only drifting encounters have.
        return value
    return min(max(value + offset, minimum), maximum)


def apply_precursor_to_vitals(reading: VitalReading, precursor: Precursor, elapsed_seconds: float) -> VitalReading:
    share = ramp(precursor, elapsed_seconds)
    if not share:
        return reading
    return replace(
        reading,
        heart_rate=_shift("heart_rate", reading.heart_rate, precursor.heart_rate * share),
        respiratory_rate=_shift("respiratory_rate", reading.respiratory_rate, precursor.respiratory_rate * share),
        spo2=_shift("spo2", reading.spo2, precursor.spo2 * share),
    )


def apply_precursor_to_blood_pressure(reading: BloodPressureReading, precursor: Precursor, elapsed_seconds: float) -> BloodPressureReading:
    share = ramp(precursor, elapsed_seconds)
    if not share:
        return reading
    systolic = _shift("systolic_bp", reading.systolic, precursor.systolic_bp * share)
    return replace(reading, systolic=reading.systolic if systolic is None else systolic)


def apply_precursor_to_bedside(reading: BedsideReading, precursor: Precursor, elapsed_seconds: float) -> BedsideReading:
    if precursor == NO_PRECURSOR or elapsed_seconds >= FEATURE_WINDOW_SECONDS:
        return reading
    share = ramp(precursor, elapsed_seconds)
    temperature = _shift("temperature", reading.temperature, precursor.temperature * share)
    oxygen_on = precursor.oxygen_from_seconds is not None and elapsed_seconds >= precursor.oxygen_from_seconds
    confused = precursor.confusion_from_seconds is not None and elapsed_seconds >= precursor.confusion_from_seconds
    return replace(
        reading,
        temperature=None if temperature is None else round(temperature, 1),
        inhaled_oxygen_concentration=precursor.inhaled_oxygen_concentration if oxygen_on else reading.inhaled_oxygen_concentration,
        consciousness_level=CONFUSED if confused else reading.consciousness_level,
    )
