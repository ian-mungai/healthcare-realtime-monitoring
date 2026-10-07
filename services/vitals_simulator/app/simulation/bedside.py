"""The bedside measures of each observation set: body temperature, inhaled oxygen concentration and ACVPU.

BIDMC has none of them, so the simulator generates them once per observation set, on the blood-pressure interval.
Values start from the patient's baseline (room air, alert) with small seeded noise; scenario.apply_bedside_scenario
then applies the encounter's scenario. The noise is seeded by patient and run, so a batch rerun repeats it.

Each patient's temperature baseline is seeded by their Synthea ID. Synthea records temperature only at illness visits
(values of 37.2 to 41.0 degrees Celsius in the local cohort), so its values are not a resting baseline.
"""

import hashlib
from dataclasses import dataclass

import numpy as np

ROOM_AIR_PERCENT = 21.0
ALERT = 0
TEMPERATURE_NOISE_SD = 0.1
BASELINE_MEAN = 36.8
BASELINE_SD = 0.3
BASELINE_RANGE = (36.3, 37.3)


def baseline_temperature(synthea_patient_id: str) -> float:
    """The patient's resting temperature in degrees Celsius, the same on every run and in every environment."""
    digest = hashlib.sha256(f"temperature-baseline:{synthea_patient_id}".encode()).digest()
    value = np.random.default_rng(int.from_bytes(digest[:8], "big")).normal(BASELINE_MEAN, BASELINE_SD)
    return round(float(min(max(value, BASELINE_RANGE[0]), BASELINE_RANGE[1])), 1)


@dataclass(frozen=True)
class BedsideReading:
    temperature: float | None = None
    inhaled_oxygen_concentration: float | None = None
    consciousness_level: int | None = None


class BedsideCadence:
    """Emit one bedside observation set per interval, the first at the start of the encounter."""

    def __init__(self, baseline_temperature: float, seed_key: str, interval_seconds: int):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        digest = hashlib.sha256(f"bedside:{seed_key}".encode()).digest()
        self.rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        self.baseline_temperature = baseline_temperature
        self.interval_seconds = interval_seconds
        self.last_emitted_interval = -1

    def get_reading(self, elapsed_seconds: float) -> BedsideReading | None:
        interval = int(elapsed_seconds // self.interval_seconds)
        if interval <= self.last_emitted_interval:
            return None
        self.last_emitted_interval = interval
        temperature = round(float(self.baseline_temperature + self.rng.normal(0.0, TEMPERATURE_NOISE_SD)), 1)
        return BedsideReading(temperature=temperature, inhaled_oxygen_concentration=ROOM_AIR_PERCENT, consciousness_level=ALERT)
