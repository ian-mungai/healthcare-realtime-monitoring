import pytest

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext
from services.vitals_simulator.app.simulation.realtime_cohort_runner import (
    PatientSimulation,
    SimulatorSettings,
    get_available_cycle_count,
    get_replay_reading,
    parse_bool,
    parse_optional_positive_int,
    parse_positive_float,
)


def build_context(patient_id: str) -> FHIRPatientContext:
    return FHIRPatientContext(
        synthea_patient_id=f"synthea-{patient_id}",
        hapi_patient_id=patient_id,
        synthea_encounter_id=f"synthea-encounter-{patient_id}",
        hapi_encounter_id=f"encounter-{patient_id}",
    )


def test_available_cycle_count_uses_shortest_record():
    simulations = [
        PatientSimulation(context=build_context("1001"), bidmc_record_number=1, readings=[1, 2, 3], bp_cadence=None),
        PatientSimulation(context=build_context("1003"), bidmc_record_number=2, readings=[1, 2], bp_cadence=None),
        PatientSimulation(context=build_context("1005"), bidmc_record_number=3, readings=[1, 2, 3, 4], bp_cadence=None),
    ]
    assert get_available_cycle_count(simulations) == 2


def test_available_cycle_count_rejects_empty_cohort():
    with pytest.raises(RuntimeError, match="Patient simulation cohort is empty"):
        get_available_cycle_count([])


@pytest.mark.parametrize(
    ("value", "expected"), [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("false", False), ("FALSE", False), ("0", False), ("no", False)]
)
def test_parse_bool(value: str, expected: bool):
    assert parse_bool(value, False) is expected


def test_parse_bool_uses_default():
    assert parse_bool(None, True) is True


def test_parse_bool_rejects_invalid_value():
    with pytest.raises(ValueError, match="Invalid boolean value"):
        parse_bool("invalid", False)


def test_parse_optional_positive_int():
    assert parse_optional_positive_int("10", 5) == 10


def test_parse_optional_positive_int_supports_unlimited():
    assert parse_optional_positive_int("unlimited", 10) is None


def test_parse_optional_positive_int_rejects_zero():
    with pytest.raises(ValueError, match="greater than zero"):
        parse_optional_positive_int("0", 10)


def test_parse_positive_float():
    assert parse_positive_float("0.5", 1.0) == 0.5


def test_parse_positive_float_rejects_zero():
    with pytest.raises(ValueError, match="greater than zero"):
        parse_positive_float("0", 1.0)


def test_simulator_settings_support_unlimited_replay():
    settings = SimulatorSettings(interval_seconds=1.0, bp_interval_seconds=300, max_cycles=None, replay=True)
    assert settings.max_cycles is None
    assert settings.replay is True


def test_get_replay_reading_first_epoch_preserves_offset():
    reading = VitalReading(source_record_id="bidmc01n", offset_seconds=5, heart_rate=80.0, respiratory_rate=18.0, spo2=98.0)
    replayed = get_replay_reading(reading, replay_index=0, available_cycles=600)
    assert replayed.offset_seconds == 5


def test_get_replay_reading_second_epoch_advances_offset():
    reading = VitalReading(source_record_id="bidmc01n", offset_seconds=5, heart_rate=80.0, respiratory_rate=18.0, spo2=98.0)
    replayed = get_replay_reading(reading, replay_index=1, available_cycles=600)
    assert replayed.offset_seconds == 605


def test_get_replay_reading_does_not_modify_original():
    reading = VitalReading(source_record_id="bidmc01n", offset_seconds=5, heart_rate=80.0, respiratory_rate=18.0, spo2=98.0)
    get_replay_reading(reading, replay_index=2, available_cycles=600)
    assert reading.offset_seconds == 5


def test_replay_boundary_is_continuous():
    last_epoch_reading = VitalReading(source_record_id="bidmc01n", offset_seconds=480, heart_rate=80.0, respiratory_rate=18.0, spo2=98.0)
    first_next_epoch_reading = VitalReading(source_record_id="bidmc01n", offset_seconds=0, heart_rate=80.0, respiratory_rate=18.0, spo2=98.0)
    last_epoch = get_replay_reading(last_epoch_reading, replay_index=0, available_cycles=481)
    next_epoch = get_replay_reading(first_next_epoch_reading, replay_index=1, available_cycles=481)
    assert last_epoch.offset_seconds == 480
    assert next_epoch.offset_seconds == 481
    assert next_epoch.offset_seconds == last_epoch.offset_seconds + 1
