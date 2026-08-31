import json
from dataclasses import asdict, dataclass
from pathlib import Path

BLOOD_PRESSURE_PANEL_CODE = "85354-9"
SYSTOLIC_CODE = "8480-6"
DIASTOLIC_CODE = "8462-4"

BLOOD_PRESSURE_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "blood_pressure_readings.json"


@dataclass(frozen=True)
class BloodPressureReading:
    source_patient_id: str
    source_observation_id: str | None
    systolic: float
    diastolic: float

    def to_dict(self) -> dict:
        return asdict(self)


def get_coding_codes(resource: dict) -> set[str]:
    return {coding.get("code") for coding in resource.get("code", {}).get("coding", []) if coding.get("code")}


def get_component_value(observation: dict, loinc_code: str) -> float | None:
    for component in observation.get("component", []):
        codes = {coding.get("code") for coding in component.get("code", {}).get("coding", [])}
        if loinc_code not in codes:
            continue
        value = component.get("valueQuantity", {}).get("value")
        if value is not None:
            return float(value)
    return None


def extract_blood_pressure_readings(bundle: dict) -> list[BloodPressureReading]:
    patient_id = None
    readings = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            patient_id = resource.get("id")
            break
    if not patient_id:
        raise RuntimeError("No Patient resource found in Synthea bundle")
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") != "Observation":
            continue
        if BLOOD_PRESSURE_PANEL_CODE not in get_coding_codes(resource):
            continue
        systolic = get_component_value(resource, SYSTOLIC_CODE)
        diastolic = get_component_value(resource, DIASTOLIC_CODE)
        if systolic is None or diastolic is None:
            continue
        readings.append(BloodPressureReading(source_patient_id=patient_id, source_observation_id=resource.get("id"), systolic=systolic, diastolic=diastolic))
    return readings


def load_synthea_blood_pressure_readings() -> list[BloodPressureReading]:
    if not BLOOD_PRESSURE_DATA_PATH.exists():
        raise RuntimeError(f"Blood pressure dataset not found: {BLOOD_PRESSURE_DATA_PATH}")
    with BLOOD_PRESSURE_DATA_PATH.open(encoding="utf-8") as file:
        raw_readings = json.load(file)
    readings = [
        BloodPressureReading(
            source_patient_id=reading["source_patient_id"],
            source_observation_id=reading.get("source_observation_id"),
            systolic=float(reading["systolic"]),
            diastolic=float(reading["diastolic"]),
        )
        for reading in raw_readings
    ]
    if not readings:
        raise RuntimeError("No Synthea blood pressure observations found")
    return readings
