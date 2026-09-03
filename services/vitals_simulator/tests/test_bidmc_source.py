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


def test_build_record_name():
    assert build_record_name(1) == "bidmc01n"

    assert build_record_name(53) == "bidmc53n"


def test_invalid_record_number():
    with pytest.raises(ValueError):
        build_record_name(0)

    with pytest.raises(ValueError):
        build_record_name(54)


def test_normalize_optional_float():
    assert normalize_optional_float(94.0) == 94.0

    assert normalize_optional_float(np.nan) is None


def test_normalize_channel_name():
    assert normalize_channel_name("HR,") == "HR"

    assert normalize_channel_name("RESP,") == "RESP"

    assert normalize_channel_name("SpO2,") == "SPO2"

    assert normalize_channel_name(" HR, ") == "HR"


def test_find_channel_index_with_bidmc_names():
    signal_names = ["HR,", "PULSE,", "RESP,", "SpO2,"]

    assert find_channel_index(signal_names, {"HR"}) == 0

    assert find_channel_index(signal_names, {"RESP", "RR"}) == 2

    assert find_channel_index(signal_names, {"SPO2"}) == 3


def test_fetch_remote_bidmc_record_uses_s3_cache(monkeypatch):
    cached = [VitalReading("bidmc01n", 0, 82.0, 19.0, 98.0)]
    monkeypatch.setattr(source, "load_cached_bidmc_record", lambda record_name: cached)

    def remote_fetch(*args, **kwargs):
        pytest.fail("PhysioNet should not be called on a cache hit")

    monkeypatch.setattr(source.wfdb, "rdsamp", remote_fetch)

    assert fetch_remote_bidmc_record(1) == cached


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

    assert attempts == 3


def test_load_cached_bidmc_record_returns_none_when_object_is_missing(monkeypatch):
    class MissingCacheClient:
        def get_object(self, **kwargs):
            error = {"Error": {"Code": "NoSuchKey", "Message": "missing"}}
            raise ClientError(error, "GetObject")

    monkeypatch.setenv("BIDMC_CACHE_S3_BUCKET", "healthcare-test")
    monkeypatch.setattr(source.boto3, "client", lambda service_name: MissingCacheClient())

    assert source.load_cached_bidmc_record("bidmc01n") is None


def test_fetch_physionet_record_fails_after_bounded_retries(monkeypatch):
    monkeypatch.setenv("BIDMC_FETCH_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("BIDMC_FETCH_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(source.wfdb, "rdsamp", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("502 Bad Gateway")))

    with pytest.raises(RuntimeError, match="after 2 attempts"):
        source.fetch_physionet_record("bidmc01n")
