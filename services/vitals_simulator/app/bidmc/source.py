import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, replace
from typing import Any

import boto3
import numpy as np
import wfdb
from botocore.exceptions import ClientError

from services.vital_signs import REALTIME_VITAL_RANGES


class _CurrentStdoutHandler(logging.Handler):
    """Write each record to the current sys.stdout, where CloudWatch collects this runtime's output."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(f"{self.format(record)}\n")
        except (OSError, ValueError):
            self.handleError(record)


LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    _handler = _CurrentStdoutHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False

PHYSIONET_DIRECTORY = "bidmc/1.0.0"

SUPPORTED_RECORD_MIN = 1
SUPPORTED_RECORD_MAX = 53
DEFAULT_FETCH_MAX_ATTEMPTS = 5
DEFAULT_FETCH_BACKOFF_SECONDS = 2.0
DEFAULT_CACHE_PREFIX = "cache/vitals_simulator/bidmc"
# A cohort larger than the 53 records reuses them: each later epoch starts the record at a different point.
MAX_REUSE_EPOCHS = 2


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


def bidmc_source_for_position(position: int) -> tuple[int, int]:
    """Return the BIDMC record number and reuse epoch for a 1-based cohort position.

    Positions 1 to 53 use records 1 to 53 in epoch 0; positions 54 to 106 reuse them in epoch 1.
    """
    if not 1 <= position <= SUPPORTED_RECORD_MAX * MAX_REUSE_EPOCHS:
        raise ValueError(f"cohort position must be between 1 and {SUPPORTED_RECORD_MAX * MAX_REUSE_EPOCHS}")
    epoch, index = divmod(position - 1, SUPPORTED_RECORD_MAX)
    return index + 1, epoch


def rotate_readings(readings: list[VitalReading], epoch: int) -> list[VitalReading]:
    """Start a reused record partway through: epoch 1 starts halfway, keeping the original 1 Hz offsets."""
    if epoch == 0 or not readings:
        return list(readings)
    shift = (len(readings) * epoch // MAX_REUSE_EPOCHS) % len(readings)
    values = readings[shift:] + readings[:shift]
    return [replace(value, offset_seconds=original.offset_seconds) for original, value in zip(readings, values, strict=True)]


# Seeded variation for a reused record: a fixed per-record offset of at least the minimum, plus per-reading noise.
# (minimum offset, maximum offset, noise standard deviation) per vital.
REUSE_VARIATION = {"heart_rate": (2.0, 8.0, 1.0), "respiratory_rate": (1.0, 3.0, 0.5), "spo2": (0.5, 2.0, 0.3)}


def vary_reused_readings(readings: list[VitalReading], record_number: int, epoch: int) -> list[VitalReading]:
    """Give a reused record its own vitals, so reused patients do not share feature-window values with the first use.

    Epoch 0 keeps the source values. Later epochs add a seeded offset per vital and small noise per reading. The same
    record and epoch always give the same values. Values outside the processor's range, such as dropouts, stay as they
    are so the processor still rejects them; varied values are kept inside the range.
    """
    if epoch == 0:
        return list(readings)
    digest = hashlib.sha256(f"bidmc-reuse:{record_number}:{epoch}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    offsets = {name: rng.choice((-1.0, 1.0)) * rng.uniform(low, high) for name, (low, high, _noise) in REUSE_VARIATION.items()}
    varied = []
    for reading in readings:
        values = {}
        for name, (_low, _high, noise) in REUSE_VARIATION.items():
            value = getattr(reading, name)
            minimum, maximum = REALTIME_VITAL_RANGES[name]
            if value is None or not minimum <= value <= maximum:
                values[name] = value
                continue
            values[name] = round(min(max(value + offsets[name] + rng.normal(0.0, noise), minimum), maximum), 1)
        varied.append(replace(reading, **values))
    return varied


# Seeded variation between runs of the same patient: (offset standard deviation, noise standard deviation) per vital.
RUN_VARIATION = {"heart_rate": (3.0, 0.5), "respiratory_rate": (1.0, 0.3), "spo2": (0.5, 0.2)}


def vary_run_readings(readings: list[VitalReading], run_key: str) -> list[VitalReading]:
    """Give one run its own stretch of the record and its own small vital offsets, so a patient's runs differ.

    The run starts at a seeded point of the record (the 1 Hz offsets stay), and each vital gets a seeded offset plus
    small noise per reading. The same run key always gives the same values. Values outside the processor's range, such
    as dropouts, stay as they are so the processor still rejects them; varied values are kept inside the range.
    """
    if not readings:
        return []
    digest = hashlib.sha256(f"bidmc-run:{run_key}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    shift = int(rng.integers(len(readings)))
    rotated = readings[shift:] + readings[:shift]
    offsets = {name: rng.normal(0.0, offset_sd) for name, (offset_sd, _noise) in RUN_VARIATION.items()}
    varied = []
    for original, reading in zip(readings, rotated, strict=True):
        values = {}
        for name, (_offset_sd, noise) in RUN_VARIATION.items():
            value = getattr(reading, name)
            minimum, maximum = REALTIME_VITAL_RANGES[name]
            if value is None or not minimum <= value <= maximum:
                values[name] = value
                continue
            values[name] = round(min(max(value + offsets[name] + rng.normal(0.0, noise), minimum), maximum), 1)
        varied.append(replace(reading, offset_seconds=original.offset_seconds, **values))
    return varied


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

    # Some headers (bidmc19n) put stray format fields before the name; the name is then the last word.
    for index, signal_name in enumerate(signal_names):
        words = signal_name.split()
        if len(words) > 1 and normalize_channel_name(words[-1]) in normalized_candidates:
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
        LOGGER.info(f"Loaded cached BIDMC record: s3://{bucket}/{key}")
        return readings
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return None
        LOGGER.warning(f"Unable to read BIDMC cache for {record_name}: {error}")
        return None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        LOGGER.warning(f"Ignoring invalid BIDMC cache for {record_name}: {error}")
        return None


def cache_bidmc_record(record_name: str, readings: list[VitalReading]) -> None:
    location = get_cache_location(record_name)
    if not location:
        return
    bucket, key = location
    body = json.dumps([reading.to_dict() for reading in readings], separators=(",", ":")).encode("utf-8")
    try:
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
        LOGGER.info(f"Cached BIDMC record: s3://{bucket}/{key}")
    except ClientError as error:
        LOGGER.warning(f"Unable to write BIDMC cache for {record_name}: {error}")


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
            LOGGER.warning(f"PhysioNet fetch failed for {record_name} (attempt {attempt}/{max_attempts}): {error}. Retrying in {delay:.1f}s")
            time.sleep(delay)

    raise RuntimeError(f"PhysioNet fetch failed for {record_name}")


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

    LOGGER.info(f"Fetching remote PhysioNet record: {record_name}")

    signals, fields = fetch_physionet_record(record_name)

    signal_names = fields["sig_name"]

    sampling_frequency = float(fields["fs"])

    LOGGER.info(f"Sampling frequency: {sampling_frequency} Hz")

    LOGGER.info(f"Signal names: {signal_names}")

    LOGGER.info(f"Samples: {signals.shape[0]}")

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
