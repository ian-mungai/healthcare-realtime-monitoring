from datetime import UTC, datetime

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.simulation.bedside import BedsideCadence
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence
from testkit import expect


def build_test_reading(offset_seconds: int) -> VitalReading:
    return VitalReading(source_record_id="bidmc01n", offset_seconds=offset_seconds, heart_rate=94.0, respiratory_rate=25.0, spo2=97.0)


def test_event_contains_bp_when_due():
    bp_readings = [BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    event = build_simulator_event(build_test_reading(0), "patient_123", "encounter_456", simulation_start, cadence)
    codes = {observation["code"]["coding"][0]["code"] for observation in event.observations}

    expect.equal(event.observation_count, 4)
    expect.is_in("85354-9", codes)


def test_event_excludes_bp_between_intervals():
    bp_readings = [BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    event = build_simulator_event(build_test_reading(1), "patient_123", "encounter_456", simulation_start, cadence)
    codes = {observation["code"]["coding"][0]["code"] for observation in event.observations}

    expect.equal(event.observation_count, 3)
    expect.not_in("85354-9", codes)


def test_event_uses_publication_elapsed_time_for_bp_cadence():
    bp_readings = [BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    first_event = build_simulator_event(build_test_reading(0), "patient_123", "encounter_456", simulation_start, cadence, bp_elapsed_seconds=0)
    next_event = build_simulator_event(build_test_reading(60), "patient_123", "encounter_456", simulation_start, cadence, bp_elapsed_seconds=300)

    expect.equal(first_event.observation_count, 4)
    expect.equal(next_event.observation_count, 4)


def test_bp_observation_contains_systolic_and_diastolic():
    bp_readings = [BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)]
    cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    event = build_simulator_event(build_test_reading(0), "patient_123", "encounter_456", simulation_start, cadence)
    bp_observation = next(observation for observation in event.observations if observation["code"]["coding"][0]["code"] == "85354-9")
    component_codes = {component["code"]["coding"][0]["code"] for component in bp_observation["component"]}

    expect.equal(component_codes, {"8480-6", "8462-4"})


def test_event_adds_the_bedside_observation_set_with_blood_pressure():
    cadence = BloodPressureCadence(readings=[BloodPressureReading("synthea_patient_1", "bp_1", 124.0, 78.0)], interval_seconds=300)
    bedside = BedsideCadence(baseline_temperature=36.8, seed_key="seed:patient:run-1", interval_seconds=300)
    simulation_start = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    due = build_simulator_event(build_test_reading(0), "patient_123", "encounter_456", simulation_start, cadence, bedside_cadence=bedside)
    between = build_simulator_event(build_test_reading(1), "patient_123", "encounter_456", simulation_start, cadence, bedside_cadence=bedside)
    by_code = {observation["code"]["coding"][0]["code"]: observation for observation in due.observations}

    expect.equal(due.observation_count, 7)
    expect.equal(between.observation_count, 3)
    expect.equal(by_code["8310-5"]["valueQuantity"]["code"], "Cel")
    expect.equal(by_code["3150-0"]["valueQuantity"]["value"], 21.0)
    expect.equal(by_code["67775-7"]["valueCodeableConcept"]["coding"][0], {"system": "http://loinc.org", "code": "LA9340-6", "display": "Alert"})
    expect.equal(len({observation["identifier"][0]["value"] for observation in due.observations}), 7)
