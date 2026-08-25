from dataclasses import asdict, dataclass

import numpy as np
import wfdb

PHYSIONET_DIRECTORY = "bidmc/1.0.0"

SUPPORTED_RECORD_MIN = 1
SUPPORTED_RECORD_MAX = 53


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


def fetch_remote_bidmc_record(record_number: int) -> list[VitalReading]:
    """
    Retrieve one BIDMC numerics record remotely
    from PhysioNet using WFDB.

    No permanent local BIDMC dataset is required.
    """
    record_name = build_record_name(record_number)

    print(f"Fetching remote PhysioNet record: {record_name}")

    signals, fields = wfdb.rdsamp(record_name, pn_dir=PHYSIONET_DIRECTORY)

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

    return readings
