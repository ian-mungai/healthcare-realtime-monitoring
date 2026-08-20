from datetime import UTC, datetime

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence


def build_test_reading(offset_seconds: int) -> VitalReading:
    return VitalReading(
        source_record_id="bidmc01n",
        offset_seconds=offset_seconds,
        heart_rate=94.0,
        respiratory_rate=25.0,
        spo2=97.0,
    )


def test_event_contains_bp_when_due():
    bp_readings = [BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    event = build_simulator_event(build_test_reading(0), "patient_123", "encounter_456", simulation_start, cadence)
    codes = {observation["code"]["coding"][0]["code"] for observation in event.observations}

    assert event.observation_count == 4
    assert "85354-9" in codes


def test_event_excludes_bp_between_intervals():
    bp_readings = [BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    event = build_simulator_event(build_test_reading(1), "patient_123", "encounter_456", simulation_start, cadence)
    codes = {observation["code"]["coding"][0]["code"] for observation in event.observations}

    assert event.observation_count == 3
    assert "85354-9" not in codes


def test_bp_observation_contains_systolic_and_diastolic():
    bp_readings = [BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    event = build_simulator_event(build_test_reading(0), "patient_123", "encounter_456", simulation_start, cadence)
    bp_observation = next(observation for observation in event.observations if observation["code"]["coding"][0]["code"] == "85354-9")
    component_codes = {component["code"]["coding"][0]["code"] for component in bp_observation["component"]}

    assert component_codes == {"8480-6", "8462-4"}