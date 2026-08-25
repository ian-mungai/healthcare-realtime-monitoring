from datetime import UTC, datetime, timedelta
from typing import Any

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading

FHIR_OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"

HEART_RATE = {"loinc_code": "8867-4", "display": "Heart rate", "unit": "beats/minute", "ucum_code": "/min"}
RESPIRATORY_RATE = {"loinc_code": "9279-1", "display": "Respiratory rate", "unit": "breaths/minute", "ucum_code": "/min"}
SPO2 = {"loinc_code": "2708-6", "display": "Oxygen saturation in Arterial blood", "unit": "%", "ucum_code": "%"}
BLOOD_PRESSURE = {"loinc_code": "85354-9", "display": "Blood pressure systolic and diastolic"}
SYSTOLIC_BP = {"loinc_code": "8480-6", "display": "Systolic blood pressure"}
DIASTOLIC_BP = {"loinc_code": "8462-4", "display": "Diastolic blood pressure"}


def normalize_measurement(value: float | None, decimals: int = 1) -> float | None:
    if value is None:
        return None

    return round(float(value), decimals)


def build_effective_datetime(simulation_start: datetime, offset_seconds: int) -> str:
    if simulation_start.tzinfo is None:
        raise ValueError("simulation_start must be timezone-aware")

    effective_time = simulation_start + timedelta(seconds=offset_seconds)

    return effective_time.isoformat()


def build_observation(
    patient_id: str,
    encounter_id: str,
    effective_datetime: str,
    code: str,
    display: str,
    value: float,
    unit: str,
    ucum_code: str,
    source_record_id: str,
    source_offset_seconds: int,
) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": FHIR_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs", "display": "Vital Signs"}]}],
        "code": {"coding": [{"system": LOINC_SYSTEM, "code": code, "display": display}], "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": effective_datetime,
        "valueQuantity": {"value": value, "unit": unit, "system": UCUM_SYSTEM, "code": ucum_code},
        "extension": [
            {"url": "https://example.org/fhir/StructureDefinition/source_record_id", "valueString": source_record_id},
            {"url": "https://example.org/fhir/StructureDefinition/source_offset_seconds", "valueInteger": source_offset_seconds},
        ],
    }


def build_blood_pressure_observation(
    patient_id: str, encounter_id: str, effective_datetime: str, reading: BloodPressureReading, source_offset_seconds: int
) -> dict[str, Any]:
    systolic = normalize_measurement(reading.systolic)
    diastolic = normalize_measurement(reading.diastolic)

    if systolic is None or diastolic is None:
        raise ValueError("Blood pressure requires both systolic and diastolic values")

    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": FHIR_OBSERVATION_CATEGORY_SYSTEM, "code": "vital-signs", "display": "Vital Signs"}]}],
        "code": {
            "coding": [{"system": LOINC_SYSTEM, "code": BLOOD_PRESSURE["loinc_code"], "display": BLOOD_PRESSURE["display"]}],
            "text": BLOOD_PRESSURE["display"],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": effective_datetime,
        "component": [
            {
                "code": {"coding": [{"system": LOINC_SYSTEM, "code": SYSTOLIC_BP["loinc_code"], "display": SYSTOLIC_BP["display"]}]},
                "valueQuantity": {"value": systolic, "unit": "mmHg", "system": UCUM_SYSTEM, "code": "mm[Hg]"},
            },
            {
                "code": {"coding": [{"system": LOINC_SYSTEM, "code": DIASTOLIC_BP["loinc_code"], "display": DIASTOLIC_BP["display"]}]},
                "valueQuantity": {"value": diastolic, "unit": "mmHg", "system": UCUM_SYSTEM, "code": "mm[Hg]"},
            },
        ],
        "extension": [
            {"url": "https://example.org/fhir/StructureDefinition/source_record_id", "valueString": reading.source_observation_id or "synthea_bp"},
            {"url": "https://example.org/fhir/StructureDefinition/source_offset_seconds", "valueInteger": source_offset_seconds},
        ],
    }


def build_observations_from_reading(reading: VitalReading, patient_id: str, encounter_id: str, simulation_start: datetime) -> list[dict[str, Any]]:
    effective_datetime = build_effective_datetime(simulation_start, reading.offset_seconds)
    observations = []

    heart_rate = normalize_measurement(reading.heart_rate)

    if heart_rate is not None:
        observations.append(
            build_observation(
                patient_id=patient_id,
                encounter_id=encounter_id,
                effective_datetime=effective_datetime,
                code=HEART_RATE["loinc_code"],
                display=HEART_RATE["display"],
                value=heart_rate,
                unit=HEART_RATE["unit"],
                ucum_code=HEART_RATE["ucum_code"],
                source_record_id=reading.source_record_id,
                source_offset_seconds=reading.offset_seconds,
            )
        )

    respiratory_rate = normalize_measurement(reading.respiratory_rate)

    if respiratory_rate is not None:
        observations.append(
            build_observation(
                patient_id=patient_id,
                encounter_id=encounter_id,
                effective_datetime=effective_datetime,
                code=RESPIRATORY_RATE["loinc_code"],
                display=RESPIRATORY_RATE["display"],
                value=respiratory_rate,
                unit=RESPIRATORY_RATE["unit"],
                ucum_code=RESPIRATORY_RATE["ucum_code"],
                source_record_id=reading.source_record_id,
                source_offset_seconds=reading.offset_seconds,
            )
        )

    spo2 = normalize_measurement(reading.spo2)

    if spo2 is not None:
        observations.append(
            build_observation(
                patient_id=patient_id,
                encounter_id=encounter_id,
                effective_datetime=effective_datetime,
                code=SPO2["loinc_code"],
                display=SPO2["display"],
                value=spo2,
                unit=SPO2["unit"],
                ucum_code=SPO2["ucum_code"],
                source_record_id=reading.source_record_id,
                source_offset_seconds=reading.offset_seconds,
            )
        )

    return observations


def utc_now() -> datetime:
    return datetime.now(UTC)
