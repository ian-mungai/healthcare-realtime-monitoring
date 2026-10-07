"""NEWS2, the Royal College of Physicians' National Early Warning Score 2 (2017), scored from one observation set.

Failure modes (written before the code):

1. A boundary value lands in the wrong band: each parameter follows the published bands, using SpO2 scale 1.
2. A measured value between whole numbers (heart rate 90.5) falls between bands: bands are treated as continuous.
3. Supplemental oxygen is any inhaled concentration above room air (21%) and scores 2.
4. Any consciousness level other than Alert (C, V, P or U) scores 3.
5. A missing parameter cannot silently score 0: the total is None unless all seven are present.
"""

import pytest

from services.news2 import news2_parameter_score, news2_score
from testkit import expect


@pytest.mark.parametrize(
    ("parameter", "value", "points"),
    [
        ("respiratory_rate", 8, 3),
        ("respiratory_rate", 9, 1),
        ("respiratory_rate", 11, 1),
        ("respiratory_rate", 12, 0),
        ("respiratory_rate", 20, 0),
        ("respiratory_rate", 21, 2),
        ("respiratory_rate", 24, 2),
        ("respiratory_rate", 25, 3),
        ("spo2", 91, 3),
        ("spo2", 92, 2),
        ("spo2", 93, 2),
        ("spo2", 94, 1),
        ("spo2", 95, 1),
        ("spo2", 96, 0),
        ("systolic_bp", 90, 3),
        ("systolic_bp", 91, 2),
        ("systolic_bp", 100, 2),
        ("systolic_bp", 101, 1),
        ("systolic_bp", 110, 1),
        ("systolic_bp", 111, 0),
        ("systolic_bp", 219, 0),
        ("systolic_bp", 220, 3),
        ("heart_rate", 40, 3),
        ("heart_rate", 41, 1),
        ("heart_rate", 50, 1),
        ("heart_rate", 51, 0),
        ("heart_rate", 90, 0),
        ("heart_rate", 90.5, 1),
        ("heart_rate", 110, 1),
        ("heart_rate", 111, 2),
        ("heart_rate", 130, 2),
        ("heart_rate", 131, 3),
        ("temperature", 35.0, 3),
        ("temperature", 35.1, 1),
        ("temperature", 36.0, 1),
        ("temperature", 36.1, 0),
        ("temperature", 38.0, 0),
        ("temperature", 38.1, 1),
        ("temperature", 39.0, 1),
        ("temperature", 39.1, 2),
        ("inhaled_oxygen_concentration", 21, 0),
        ("inhaled_oxygen_concentration", 24, 2),
        ("consciousness_level", 0, 0),
        ("consciousness_level", 1, 3),
        ("consciousness_level", 4, 3),
    ],
)
def test_each_parameter_follows_the_published_bands(parameter: str, value: float, points: int) -> None:
    expect.equal(news2_parameter_score(parameter, value), points)


def test_the_total_needs_all_seven_parameters() -> None:
    observation_set = {
        "respiratory_rate": 22,
        "spo2": 95,
        "inhaled_oxygen_concentration": 21,
        "systolic_bp": 105,
        "heart_rate": 115,
        "consciousness_level": 0,
        "temperature": 38.3,
    }

    expect.equal(news2_score(observation_set), 2 + 1 + 0 + 1 + 2 + 0 + 1)
    expect.equal(news2_score({**observation_set, "temperature": None}), None)
