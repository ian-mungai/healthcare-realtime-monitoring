import pytest

from services.vitals_simulator.app.synthea.blood_pressure import (
    BloodPressureReading,
    extract_blood_pressure_readings,
    get_component_value,
    readings_for_patient,
)
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence


def sample_bp_bundle() -> dict:
    return {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "synthea_patient_1"}},
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "bp_1",
                    "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
                    "component": [
                        {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]}, "valueQuantity": {"value": 124, "unit": "mmHg"}},
                        {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]}, "valueQuantity": {"value": 78, "unit": "mmHg"}},
                    ],
                }
            },
        ],
    }


def test_get_systolic_component():
    observation = sample_bp_bundle()["entry"][1]["resource"]

    assert get_component_value(observation, "8480-6") == 124.0


def test_extract_blood_pressure_reading():
    readings = extract_blood_pressure_readings(sample_bp_bundle())

    assert len(readings) == 1
    assert readings[0].systolic == 124.0
    assert readings[0].diastolic == 78.0


def test_bp_cadence_due():
    readings = [BloodPressureReading("patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=readings, interval_seconds=300)

    assert cadence.is_due(0)
    assert not cadence.is_due(1)
    assert not cadence.is_due(299)
    assert cadence.is_due(300)
    assert cadence.is_due(600)


def test_bp_cadence_returns_none_between_measurements():
    readings = [BloodPressureReading("patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=readings, interval_seconds=300)

    assert cadence.get_reading(1) is None


def test_bp_cadence_rejects_empty_readings():
    with pytest.raises(ValueError, match="At least one blood pressure reading is required"):
        BloodPressureCadence(readings=[])


def test_readings_for_patient_returns_only_matching_patient():
    readings = [
        BloodPressureReading("patient_1", "bp_1", 124.0, 78.0),
        BloodPressureReading("patient_2", "bp_2", 118.0, 72.0),
        BloodPressureReading("patient_1", "bp_3", 126.0, 80.0),
    ]

    assert readings_for_patient(readings, "patient_1") == [readings[0], readings[2]]


def test_readings_for_patient_rejects_unmapped_patient():
    readings = [BloodPressureReading("patient_1", "bp_1", 124.0, 78.0)]

    with pytest.raises(RuntimeError, match="No blood pressure readings found for Synthea patient patient_2"):
        readings_for_patient(readings, "patient_2")
