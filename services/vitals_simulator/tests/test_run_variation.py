"""Each run of a patient gets its own stretch of the patient's waveform record and its own small vital offsets.

Failure modes (written before the code):

1. Every run replays the record from the same point: a patient's six runs have identical feature windows, so an
   unplanted deterioration encounter copies the normal ones. Each run starts at its own seeded point.
2. Rotation alone keeps the record's mean: each run also gets a seeded offset per vital.
3. A rerun must repeat the study: the same run key gives the same readings; another key gives other readings.
4. A dropout outside the processor's range must stay rejected, and varied values must stay inside the range.
5. The readings keep their 1 Hz offsets, so cadences and windows are unchanged.
"""

from services.vital_signs import REALTIME_VITAL_RANGES
from services.vitals_simulator.app.bidmc.source import RUN_VARIATION, VitalReading, vary_run_readings
from testkit import expect

READINGS = [VitalReading("bidmc01n", offset, 70.0 + offset % 30, 14.0 + offset % 5, 96.0 + offset % 3) for offset in range(480)]


def mean(readings: list[VitalReading], name: str) -> float:
    values = [getattr(reading, name) for reading in readings]
    return sum(values) / len(values)


def test_runs_start_at_their_own_point_with_their_own_offsets() -> None:
    first = vary_run_readings(READINGS, "4817263:patient-1:batch-4817263-1")
    second = vary_run_readings(READINGS, "4817263:patient-1:batch-4817263-2")

    if first[0].heart_rate == second[0].heart_rate and first[10].heart_rate == second[10].heart_rate:
        expect.fail("expected: two runs start at different points of the record")
    if abs(mean(first[:300], "heart_rate") - mean(second[:300], "heart_rate")) < 0.05:
        expect.fail("expected: two runs differ in their feature-window heart-rate mean")


def test_the_same_run_key_repeats_the_readings_and_keeps_offsets() -> None:
    first = vary_run_readings(READINGS, "4817263:patient-1:batch-4817263-1")

    expect.equal(vary_run_readings(READINGS, "4817263:patient-1:batch-4817263-1"), first)
    expect.equal([reading.offset_seconds for reading in first], [reading.offset_seconds for reading in READINGS])


def test_offsets_spread_around_zero_by_the_configured_size() -> None:
    shifts = [mean(vary_run_readings(READINGS, f"seed:patient:run-{run}"), "heart_rate") - mean(READINGS, "heart_rate") for run in range(300)]
    spread = (sum(shift**2 for shift in shifts) / len(shifts)) ** 0.5

    if abs(sum(shifts) / len(shifts)) > 0.6 or not 0.6 * RUN_VARIATION["heart_rate"][0] <= spread <= 1.4 * RUN_VARIATION["heart_rate"][0]:
        expect.fail(f"expected: run offsets centred on 0 with spread near {RUN_VARIATION['heart_rate'][0]}, got {spread:.2f}")


def test_dropouts_stay_and_varied_values_stay_inside_the_ranges() -> None:
    edge = [VitalReading("bidmc01n", 0, 249.9, 2.0, 99.9), VitalReading("bidmc01n", 1, 80.0, 16.0, 99.9)]

    for run in range(50):
        varied = vary_run_readings(edge, f"run-{run}")
        expect.equal(min(reading.respiratory_rate for reading in varied if reading.respiratory_rate is not None), 2.0)
        for reading in varied:
            for name in RUN_VARIATION:
                value = getattr(reading, name)
                low, high = REALTIME_VITAL_RANGES[name]
                if value is not None and value != 2.0 and not low <= value <= high:
                    expect.fail(f"expected: {name} inside {low} to {high}, got {value}")
