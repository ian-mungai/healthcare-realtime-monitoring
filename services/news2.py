"""NEWS2, the Royal College of Physicians' National Early Warning Score 2 (2017), from one observation set.

Parameters use the shared catalog's field names. SpO2 uses scale 1. Bands are continuous, so a measured value between
whole numbers (heart rate 90.5) scores with the band above it. Supplemental oxygen is any inhaled concentration above
room air; consciousness is the ACVPU ordinal, where anything but Alert (0) scores 3. The total needs all seven
parameters, so a missing one never scores as normal.
"""

from collections.abc import Mapping

ROOM_AIR_PERCENT = 21.0
PARAMETERS = ("respiratory_rate", "spo2", "inhaled_oxygen_concentration", "systolic_bp", "heart_rate", "consciousness_level", "temperature")
# (upper bound inclusive, points), checked in order; the last band has no upper bound.
BANDS: dict[str, tuple[tuple[float, int], ...]] = {
    "respiratory_rate": ((8, 3), (11, 1), (20, 0), (24, 2), (float("inf"), 3)),
    "spo2": ((91, 3), (93, 2), (95, 1), (float("inf"), 0)),
    "systolic_bp": ((90, 3), (100, 2), (110, 1), (219, 0), (float("inf"), 3)),
    "heart_rate": ((40, 3), (50, 1), (90, 0), (110, 1), (130, 2), (float("inf"), 3)),
    "temperature": ((35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1), (float("inf"), 2)),
}


def news2_parameter_score(parameter: str, value: float) -> int:
    if parameter == "inhaled_oxygen_concentration":
        return 2 if value > ROOM_AIR_PERCENT else 0
    if parameter == "consciousness_level":
        return 0 if value == 0 else 3
    for upper, points in BANDS[parameter]:
        if value <= upper:
            return points
    raise ValueError(f"no NEWS2 band for {parameter}={value}")


def news2_score(observation_set: Mapping[str, float | None]) -> int | None:
    """The NEWS2 total, or None when any of the seven parameters is missing."""
    values = [observation_set.get(parameter) for parameter in PARAMETERS]
    if any(value is None for value in values):
        return None
    return sum(news2_parameter_score(parameter, float(value)) for parameter, value in zip(PARAMETERS, values, strict=True) if value is not None)
