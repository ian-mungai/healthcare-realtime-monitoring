from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.synthea_loader.src.load_fhir import find_patient_bundles, load_bundle

BLOOD_PRESSURE_PANEL_CODE = "85354-9"
SYSTOLIC_CODE = "8480-6"
DIASTOLIC_CODE = "8462-4"


@dataclass(frozen=True)
class BloodPressureReading:
    source_patient_id: str
    source_observation_id: str | None
    systolic: float
    diastolic: float

    def to_dict(self) -> dict:
        return asdict(self)


def get_coding_codes(resource: dict) -> set[str]:
    return {
        coding.get("code")
        for coding in resource.get("code", {}).get("coding", [])
        if coding.get("code")
    }


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

        readings.append(
            BloodPressureReading(
                source_patient_id=patient_id,
                source_observation_id=resource.get("id"),
                systolic=systolic,
                diastolic=diastolic,
            )
        )

    return readings


def load_synthea_blood_pressure_readings() -> list[BloodPressureReading]:
    patient_bundles: list[Path] = find_patient_bundles()

    if not patient_bundles:
        raise RuntimeError("No Synthea patient bundles found")

    readings = []

    for bundle_path in patient_bundles:
        bundle = load_bundle(bundle_path)
        readings.extend(extract_blood_pressure_readings(bundle))

    if not readings:
        raise RuntimeError("No complete Synthea blood pressure observations found")

    return readings
