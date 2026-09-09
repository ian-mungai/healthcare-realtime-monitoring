from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.fhir.client import FHIRPermanentError, FHIRRetryableError
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext
from services.vitals_simulator.app.fhir.publisher import PublishedSimulatorEvent
from services.vitals_simulator.app.simulation import realtime_cohort_runner
from services.vitals_simulator.app.simulation.realtime_cohort_runner import (
    CyclePublishResult,
    PatientCycleFailure,
    PatientSimulation,
    SimulatorSettings,
    get_available_cycle_count,
    get_cycle_simulation_start,
    get_replay_reading,
    load_settings,
    parse_bool,
    parse_optional_positive_int,
    parse_positive_float,
    parse_ratio,
    run_cycle,
    wait_for_next_cycle,
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


def test_parse_ratio_rejects_values_above_one():
    with pytest.raises(ValueError, match="less than or equal to one"):
        parse_ratio("1.1", 0.5)


def test_simulator_settings_support_unlimited_replay():
    settings = SimulatorSettings(interval_seconds=1.0, bp_interval_seconds=300, max_cycles=None, replay=True)
    assert settings.max_cycles is None
    assert settings.replay is True


def test_load_settings_reads_publication_resilience_controls(monkeypatch):
    monkeypatch.setenv("SIMULATOR_FHIR_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("SIMULATOR_FHIR_RETRY_BACKOFF_SECONDS", "1.5")
    monkeypatch.setenv("SIMULATOR_MAX_CONSECUTIVE_FAILED_CYCLES", "6")
    monkeypatch.setenv("SIMULATOR_FAILURE_RATIO_THRESHOLD", "0.7")

    settings = load_settings()

    assert settings.fhir_max_attempts == 4
    assert settings.fhir_retry_backoff_seconds == 1.5
    assert settings.max_consecutive_failed_cycles == 6
    assert settings.failure_ratio_threshold == 0.7


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


def test_cycle_simulation_start_makes_effective_time_equal_publication_time():
    cycle_timestamp = datetime(2026, 9, 3, 17, 0, 0, tzinfo=UTC)
    reading = VitalReading(source_record_id="bidmc01n", offset_seconds=262, heart_rate=80.0, respiratory_rate=18.0, spo2=98.0)

    simulation_start = get_cycle_simulation_start(cycle_timestamp, reading)

    assert simulation_start.isoformat() == "2026-09-03T16:55:38+00:00"


def test_publish_patient_cycle_delegates_retries_to_hapi_client(monkeypatch):
    simulation = PatientSimulation(
        context=build_context("1001"), bidmc_record_number=1, readings=[VitalReading("bidmc01n", 0, 80.0, 18.0, 98.0)], bp_cadence=None
    )
    event = object()
    calls = []
    client_settings = []

    monkeypatch.setattr(realtime_cohort_runner, "build_simulator_event", lambda **_kwargs: event)

    class FakeClient:
        def __init__(self, **kwargs):
            client_settings.append(kwargs)

    monkeypatch.setattr(realtime_cohort_runner, "HAPIFHIRClient", FakeClient)

    def publish(current_event, _client):
        calls.append(current_event)
        return PublishedSimulatorEvent("bidmc01n", 0, "1001", "encounter-1001", 3, [])

    monkeypatch.setattr(realtime_cohort_runner, "publish_simulator_event", publish)

    result = realtime_cohort_runner.publish_patient_cycle(
        simulation,
        cycle_index=0,
        replay_index=0,
        available_cycles=1,
        cycle_timestamp=datetime(2026, 9, 8, 16, 0, tzinfo=UTC),
        fhir_max_attempts=2,
        fhir_retry_backoff_seconds=0.5,
    )

    assert result.published_count == 3
    assert calls == [event]
    assert client_settings == [{"max_retries": 2, "retry_delay_seconds": 0.5}]


def test_publish_patient_cycle_does_not_retry_permanent_failure(monkeypatch):
    simulation = PatientSimulation(
        context=build_context("1001"), bidmc_record_number=1, readings=[VitalReading("bidmc01n", 0, 80.0, 18.0, 98.0)], bp_cadence=None
    )
    calls = []

    monkeypatch.setattr(realtime_cohort_runner, "build_simulator_event", lambda **_kwargs: object())
    monkeypatch.setattr(realtime_cohort_runner, "HAPIFHIRClient", lambda **_kwargs: object())

    def publish(_event, _client):
        calls.append(1)
        raise FHIRPermanentError("invalid observation")

    monkeypatch.setattr(realtime_cohort_runner, "publish_simulator_event", publish)

    with pytest.raises(FHIRPermanentError, match="invalid observation"):
        realtime_cohort_runner.publish_patient_cycle(
            simulation,
            cycle_index=0,
            replay_index=0,
            available_cycles=1,
            cycle_timestamp=datetime(2026, 9, 8, 16, 0, tzinfo=UTC),
            fhir_max_attempts=3,
            fhir_retry_backoff_seconds=0.5,
        )

    assert len(calls) == 1


def test_wait_for_next_cycle_reports_overrun(monkeypatch, capsys):
    monkeypatch.setattr(realtime_cohort_runner.time, "monotonic", lambda: 15.5)
    monkeypatch.setattr(realtime_cohort_runner.shutdown_event, "wait", lambda timeout: False)

    assert wait_for_next_cycle(cycle_started=10.0, interval_seconds=5.0) == 0.5
    assert "cycle_overrun overrun_seconds=0.500" in capsys.readouterr().out


def test_run_cycle_isolates_one_failed_patient(monkeypatch):
    simulations = [
        PatientSimulation(context=build_context(str(1001 + index)), bidmc_record_number=index + 1, readings=[], bp_cadence=None) for index in range(10)
    ]

    def publish(simulation, *_args):
        if simulation.context.hapi_patient_id == "1004":
            raise FHIRRetryableError("temporary failure")
        return PublishedSimulatorEvent("bidmc01n", 0, simulation.context.hapi_patient_id, simulation.context.hapi_encounter_id, 3, [])

    monkeypatch.setattr(realtime_cohort_runner, "publish_patient_cycle", publish)

    with ThreadPoolExecutor(max_workers=10) as executor:
        result = run_cycle(executor, simulations, cycle_index=0, replay_index=0, available_cycles=1, cycle_timestamp=datetime(2026, 9, 8, 16, 0, tzinfo=UTC))

    assert result.published_count == 9
    assert result.observation_count == 27
    assert result.failures == (PatientCycleFailure("1004", 4, "FHIRRetryableError", "temporary failure", True),)


def test_realtime_cohort_stops_only_at_consecutive_failure_threshold(monkeypatch):
    simulation = PatientSimulation(
        context=build_context("1001"), bidmc_record_number=1, readings=[VitalReading("bidmc01n", 0, 80.0, 18.0, 98.0)], bp_cadence=None
    )
    failure = PatientCycleFailure("1001", 1, "FHIRRetryableError", "temporary failure", True)
    cycle_calls = []

    monkeypatch.setattr(realtime_cohort_runner, "load_patient_simulations", lambda _interval: [simulation])
    monkeypatch.setattr(realtime_cohort_runner, "wait_for_next_cycle", lambda *_args: None)

    def degraded_cycle(**_kwargs):
        cycle_calls.append(1)
        return CyclePublishResult(0, 0, (failure,))

    monkeypatch.setattr(realtime_cohort_runner, "run_cycle", degraded_cycle)
    settings = SimulatorSettings(interval_seconds=1, bp_interval_seconds=300, max_cycles=None, replay=True, max_consecutive_failed_cycles=2)

    with pytest.raises(RuntimeError, match="2 consecutive systemic failure cycles"):
        realtime_cohort_runner.run_realtime_cohort(settings)

    assert len(cycle_calls) == 2


def test_realtime_cohort_disables_permanent_failure_and_continues(monkeypatch):
    simulations = [
        PatientSimulation(
            context=build_context(patient_id), bidmc_record_number=index, readings=[VitalReading(f"bidmc0{index}n", 0, 80.0, 18.0, 98.0)], bp_cadence=None
        )
        for index, patient_id in enumerate(("1001", "1002"), start=1)
    ]
    failure = PatientCycleFailure("1001", 1, "FHIRPermanentError", "invalid observation", False)
    active_patient_sets = []

    monkeypatch.setattr(realtime_cohort_runner, "load_patient_simulations", lambda _interval: simulations)
    monkeypatch.setattr(realtime_cohort_runner, "wait_for_next_cycle", lambda *_args: 0.0)

    def run_test_cycle(**kwargs):
        active_patient_sets.append({simulation.context.hapi_patient_id for simulation in kwargs["simulations"]})
        failures = (failure,) if len(active_patient_sets) == 1 else ()
        return CyclePublishResult(1, 3, failures)

    monkeypatch.setattr(realtime_cohort_runner, "run_cycle", run_test_cycle)
    settings = SimulatorSettings(interval_seconds=1, bp_interval_seconds=300, max_cycles=2, replay=True)

    assert realtime_cohort_runner.run_realtime_cohort(settings) == 2
    assert active_patient_sets == [{"1001", "1002"}, {"1002"}]
