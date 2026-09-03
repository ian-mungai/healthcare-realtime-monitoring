import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import boto3
import numpy as np
import wfdb
from botocore.exceptions import ClientError

PHYSIONET_DIRECTORY = "bidmc/1.0.0"

SUPPORTED_RECORD_MIN = 1
SUPPORTED_RECORD_MAX = 53
DEFAULT_FETCH_MAX_ATTEMPTS = 5
DEFAULT_FETCH_BACKOFF_SECONDS = 2.0
DEFAULT_CACHE_PREFIX = "cache/vitals_simulator/bidmc"


@dataclass(frozen=True)
class VitalReading:
    """
    One normalized 1 Hz physiological reading
    retrieved from the BIDMC dataset.
    """

    source_record_id: str
    offset_seconds: int
    heart_rate: float | None
    respiratory_rate: float | None
    spo2: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_record_number(record_number: int) -> int:
    """
    Validate the BIDMC record number.
    """
    if not (SUPPORTED_RECORD_MIN <= record_number <= SUPPORTED_RECORD_MAX):
        raise ValueError(f"BIDMC record number must be between {SUPPORTED_RECORD_MIN} and {SUPPORTED_RECORD_MAX}")

    return record_number


def build_record_name(record_number: int) -> str:
    """
    Convert:

        1

    into:

        bidmc01n
    """
    record_number = normalize_record_number(record_number)

    return f"bidmc{record_number:02d}n"


def normalize_optional_float(value: float) -> float | None:
    """
    Convert numeric values to Python floats.

    Missing BIDMC measurements are represented
    internally as None.
    """
    if np.isnan(value):
        return None

    return float(value)


def normalize_channel_name(channel_name: str) -> str:
    """
    Normalize channel names returned by BIDMC/WFDB.

    PhysioNet currently returns names such as:

        HR,
        PULSE,
        RESP,
        SpO2,

    The trailing comma is removed before matching.
    """
    return channel_name.strip().rstrip(",").strip().upper()


def find_channel_index(signal_names: list[str], candidates: set[str]) -> int:
    """
    Find a channel by normalized signal name.
    """
    normalized_names = [normalize_channel_name(name) for name in signal_names]

    normalized_candidates = {normalize_channel_name(candidate) for candidate in candidates}

    for index, signal_name in enumerate(normalized_names):
        if signal_name in normalized_candidates:
            return index

    raise ValueError(f"Could not find any of these channels: {sorted(candidates)}. Available channels: {signal_names}")


def get_cache_location(record_name: str) -> tuple[str, str] | None:
    bucket = os.getenv("BIDMC_CACHE_S3_BUCKET")
    if not bucket:
        return None
    prefix = os.getenv("BIDMC_CACHE_S3_PREFIX", DEFAULT_CACHE_PREFIX).strip("/")
    return bucket, f"{prefix}/{record_name}.json"


def deserialize_readings(payload: bytes) -> list[VitalReading]:
    values = json.loads(payload.decode("utf-8"))
    if not isinstance(values, list):
        raise ValueError("Cached BIDMC payload must be a list")
    return [VitalReading(**value) for value in values]


def load_cached_bidmc_record(record_name: str) -> list[VitalReading] | None:
    location = get_cache_location(record_name)
    if not location:
        return None
    bucket, key = location
    try:
        response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        readings = deserialize_readings(response["Body"].read())
        print(f"Loaded cached BIDMC record: s3://{bucket}/{key}")
        return readings
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return None
        print(f"Unable to read BIDMC cache for {record_name}: {error}")
        return None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Ignoring invalid BIDMC cache for {record_name}: {error}")
        return None


def cache_bidmc_record(record_name: str, readings: list[VitalReading]) -> None:
    location = get_cache_location(record_name)
    if not location:
        return
    bucket, key = location
    body = json.dumps([reading.to_dict() for reading in readings], separators=(",", ":")).encode("utf-8")
    try:
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
        print(f"Cached BIDMC record: s3://{bucket}/{key}")
    except ClientError as error:
        print(f"Unable to write BIDMC cache for {record_name}: {error}")


def fetch_physionet_record(record_name: str) -> tuple[Any, dict[str, Any]]:
    max_attempts = int(os.getenv("BIDMC_FETCH_MAX_ATTEMPTS", str(DEFAULT_FETCH_MAX_ATTEMPTS)))
    backoff_seconds = float(os.getenv("BIDMC_FETCH_BACKOFF_SECONDS", str(DEFAULT_FETCH_BACKOFF_SECONDS)))
    if max_attempts <= 0 or backoff_seconds < 0:
        raise ValueError("BIDMC retry configuration is invalid")
    for attempt in range(1, max_attempts + 1):
        try:
            return wfdb.rdsamp(record_name, pn_dir=PHYSIONET_DIRECTORY)
        except Exception as error:
            if attempt == max_attempts:
                raise RuntimeError(f"PhysioNet fetch failed for {record_name} after {max_attempts} attempts") from error
            delay = backoff_seconds * (2 ** (attempt - 1))
            print(f"PhysioNet fetch failed for {record_name} (attempt {attempt}/{max_attempts}): {error}. Retrying in {delay:.1f}s")
            time.sleep(delay)


def fetch_remote_bidmc_record(record_number: int) -> list[VitalReading]:
    """
    Retrieve one BIDMC numerics record remotely
    from PhysioNet using WFDB.

    No permanent local BIDMC dataset is required.
    """
    record_name = build_record_name(record_number)

    cached_readings = load_cached_bidmc_record(record_name)
    if cached_readings:
        return cached_readings

    print(f"Fetching remote PhysioNet record: {record_name}")

    signals, fields = fetch_physionet_record(record_name)

    signal_names = fields["sig_name"]

    sampling_frequency = float(fields["fs"])

    print(f"Sampling frequency: {sampling_frequency} Hz")

    print(f"Signal names: {signal_names}")

    print(f"Samples: {signals.shape[0]}")

    if sampling_frequency <= 0:
        raise ValueError("Invalid sampling frequency returned by PhysioNet")

    hr_index = find_channel_index(signal_names, {"HR", "HEART RATE"})

    rr_index = find_channel_index(signal_names, {"RESP", "RR", "RESPIRATORY RATE"})

    spo2_index = find_channel_index(signal_names, {"SPO2", "SPO2%", "O2 SAT"})

    readings = []

    for sample_index in range(signals.shape[0]):
        offset_seconds = int(sample_index / sampling_frequency)

        heart_rate = normalize_optional_float(signals[sample_index, hr_index])

        respiratory_rate = normalize_optional_float(signals[sample_index, rr_index])

        spo2 = normalize_optional_float(signals[sample_index, spo2_index])

        reading = VitalReading(source_record_id=record_name, offset_seconds=offset_seconds, heart_rate=heart_rate, respiratory_rate=respiratory_rate, spo2=spo2)

        readings.append(reading)

    cache_bidmc_record(record_name, readings)

    return readings
