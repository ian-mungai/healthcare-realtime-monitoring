import numpy as np
import pytest
from botocore.exceptions import ClientError

from services.vitals_simulator.app.bidmc import source
from services.vitals_simulator.app.bidmc.source import (
    VitalReading,
    build_record_name,
    fetch_remote_bidmc_record,
    find_channel_index,
    normalize_channel_name,
    normalize_optional_float,
)
from testkit import expect


def test_build_record_name():
    expect.equal(build_record_name(1), "bidmc01n")

    expect.equal(build_record_name(53), "bidmc53n")


def test_invalid_record_number():
    with pytest.raises(ValueError):
        build_record_name(0)

    with pytest.raises(ValueError):
        build_record_name(54)


def test_normalize_optional_float():
    expect.equal(normalize_optional_float(94.0), 94.0)

    expect.identical(normalize_optional_float(np.nan), None)


def test_normalize_channel_name():
    expect.equal(normalize_channel_name("HR,"), "HR")

    expect.equal(normalize_channel_name("RESP,"), "RESP")

    expect.equal(normalize_channel_name("SpO2,"), "SPO2")

    expect.equal(normalize_channel_name(" HR, "), "HR")


def test_find_channel_index_with_bidmc_names():
    signal_names = ["HR,", "PULSE,", "RESP,", "SpO2,"]

    expect.equal(find_channel_index(signal_names, {"HR"}), 0)

    expect.equal(find_channel_index(signal_names, {"RESP", "RR"}), 2)

    expect.equal(find_channel_index(signal_names, {"SPO2"}), 3)


def test_fetch_remote_bidmc_record_uses_s3_cache(monkeypatch):
    cached = [VitalReading("bidmc01n", 0, 82.0, 19.0, 98.0)]
    monkeypatch.setattr(source, "load_cached_bidmc_record", lambda record_name: cached)

    def remote_fetch(*args, **kwargs):
        pytest.fail("PhysioNet should not be called on a cache hit")

    monkeypatch.setattr(source.wfdb, "rdsamp", remote_fetch)

    expect.equal(fetch_remote_bidmc_record(1), cached)


def test_fetch_physionet_record_retries_then_succeeds(monkeypatch):
    attempts = 0

    def fetch(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("502 Bad Gateway")
        return np.array([[82.0, 19.0, 98.0]]), {"sig_name": ["HR", "RESP", "SpO2"], "fs": 1.0}

    monkeypatch.setenv("BIDMC_FETCH_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("BIDMC_FETCH_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(source.wfdb, "rdsamp", fetch)

    source.fetch_physionet_record("bidmc01n")

    expect.equal(attempts, 3)


def test_load_cached_bidmc_record_returns_none_when_object_is_missing(monkeypatch):
    class MissingCacheClient:
        def get_object(self, **kwargs):
            error = {"Error": {"Code": "NoSuchKey", "Message": "missing"}}
            raise ClientError(error, "GetObject")

    monkeypatch.setenv("BIDMC_CACHE_S3_BUCKET", "healthcare-test")
    monkeypatch.setattr(source.boto3, "client", lambda _service_name: MissingCacheClient())

    expect.identical(source.load_cached_bidmc_record("bidmc01n"), None)


def test_fetch_physionet_record_fails_after_bounded_retries(monkeypatch):
    monkeypatch.setenv("BIDMC_FETCH_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("BIDMC_FETCH_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(source.wfdb, "rdsamp", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("502 Bad Gateway")))

    with pytest.raises(RuntimeError, match="after 2 attempts"):
        source.fetch_physionet_record("bidmc01n")


@pytest.mark.parametrize(("position", "expected"), [(1, (1, 0)), (53, (53, 0)), (54, (1, 1)), (100, (47, 1))])
def test_cohort_positions_past_the_53_records_reuse_a_record_in_a_later_epoch(position, expected):
    # BIDMC has 53 numerics records; a 100-patient cohort reuses records 1 to 47 for patients 54 to 100.
    expect.equal(source.bidmc_source_for_position(position), expected)


@pytest.mark.parametrize("position", [0, -1, 107])
def test_cohort_position_outside_two_reuse_epochs_is_rejected(position):
    with pytest.raises(ValueError, match="cohort position"):
        source.bidmc_source_for_position(position)


def test_reused_record_starts_halfway_through_and_keeps_its_offsets():
    readings = [source.VitalReading("bidmc01n", offset, float(60 + offset), 16.0, 98.0) for offset in range(6)]

    expect.equal(source.rotate_readings(readings, 0), readings)
    rotated = source.rotate_readings(readings, 1)

    expect.equal([reading.offset_seconds for reading in rotated], list(range(6)))
    expect.equal([reading.heart_rate for reading in rotated], [63.0, 64.0, 65.0, 60.0, 61.0, 62.0])
    expect.equal({reading.source_record_id for reading in rotated}, {"bidmc01n"})


def test_find_channel_index_reads_the_signal_name_after_stray_header_fields():
    # PhysioNet's bidmc19n header carries format fields before the SpO2 name.
    signal_names = ["HR,", "PULSE,", "RESP,", "(-32767)/% 0 0 -32768 0 0 SpO2,"]

    expect.equal(find_channel_index(signal_names, {"SPO2", "SPO2%", "O2 SAT"}), 3)


def steady_record(record_name: str = "bidmc01n", length: int = 240) -> list[source.VitalReading]:
    return [source.VitalReading(record_name, offset, 80.0, 16.0, 96.0) for offset in range(length)]


def mean(values):
    present = [value for value in values if value is not None]
    return sum(present) / len(present)


def test_records_in_their_first_use_keep_the_source_values():
    readings = steady_record()

    expect.equal(source.vary_reused_readings(readings, 1, 0), readings)


def test_a_reused_record_gets_a_distinct_seeded_offset_and_noise():
    # Patients 54 to 100 would otherwise share their feature-window vitals with patients 1 to 47.
    readings = steady_record()
    varied = source.vary_reused_readings(readings, 1, 1)

    expect.equal(source.vary_reused_readings(readings, 1, 1), varied)
    expect.equal([reading.offset_seconds for reading in varied], [reading.offset_seconds for reading in readings])
    if abs(mean(r.heart_rate for r in varied) - 80.0) < 2.0:
        expect.fail("expected: the reused heart rate shifts by at least 2 bpm on average")
    if abs(mean(r.respiratory_rate for r in varied) - 16.0) < 1.0:
        expect.fail("expected: the reused respiratory rate shifts by at least 1 breath/min on average")
    if len({r.heart_rate for r in varied}) < 10:
        expect.fail("expected: per-reading noise, not one constant value")
    if varied == source.vary_reused_readings(steady_record("bidmc02n"), 2, 1):
        expect.fail("expected: each reused record varies differently")


def test_variation_keeps_values_inside_the_processor_ranges_and_leaves_dropouts_alone():
    readings = [source.VitalReading("bidmc01n", 0, None, 0.0, 100.0), source.VitalReading("bidmc01n", 1, 249.5, 79.5, 99.9)]

    varied = source.vary_reused_readings(readings, 1, 1)

    expect.equal(varied[0].heart_rate, None)
    expect.equal(varied[0].respiratory_rate, 0.0)
    for reading in varied[1:]:
        if not (20 <= reading.heart_rate <= 250 and 4 <= reading.respiratory_rate <= 80 and 50 <= reading.spo2 <= 100):
            expect.fail(f"expected: varied values inside the processor ranges, got {reading}")
    if varied[0].spo2 > 100:
        expect.fail("expected: SpO2 never above 100")
