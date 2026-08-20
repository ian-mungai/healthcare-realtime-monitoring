import pytest

from services.vitals_simulator.app.synthea.blood_pressure import (
    BloodPressureReading,
    extract_blood_pressure_readings,
    get_component_value,
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
                        {
                            "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                            "valueQuantity": {"value": 124, "unit": "mmHg"},
                        },
                        {
                            "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                            "valueQuantity": {"value": 78, "unit": "mmHg"},
                        },
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