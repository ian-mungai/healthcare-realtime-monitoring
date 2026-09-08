import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import Event

from services.vitals_simulator.app.bidmc.source import VitalReading, fetch_remote_bidmc_record
from services.vitals_simulator.app.fhir.client import FHIRRetryableError, HAPIFHIRClient
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext, get_patient_cohort
from services.vitals_simulator.app.fhir.observation import utc_now
from services.vitals_simulator.app.fhir.publisher import PublishedSimulatorEvent, publish_simulator_event
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import load_synthea_blood_pressure_readings, readings_for_patient
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence

COHORT_SIZE = 10
DEFAULT_INTERVAL_SECONDS = 1.0
DEFAULT_BP_INTERVAL_SECONDS = 300
DEFAULT_MAX_CYCLES = 10
DEFAULT_PUBLISH_MAX_ATTEMPTS = 2
DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES = 3

shutdown_event = Event()


@dataclass
class SimulatorSettings:
    interval_seconds: float
    bp_interval_seconds: int
    max_cycles: int | None
    replay: bool
    publish_max_attempts: int = DEFAULT_PUBLISH_MAX_ATTEMPTS
    publish_retry_backoff_seconds: float = DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS
    max_consecutive_failed_cycles: int = DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES


@dataclass
class PatientSimulation:
    context: FHIRPatientContext
    bidmc_record_number: int
    readings: list[VitalReading]
    bp_cadence: BloodPressureCadence


@dataclass(frozen=True)
class PatientCycleFailure:
    patient_id: str
    bidmc_record_number: int
    error_type: str
    error_message: str
    retryable: bool


@dataclass(frozen=True)
class CyclePublishResult:
    published_count: int
    observation_count: int
    failures: tuple[PatientCycleFailure, ...]


def parse_optional_positive_int(value: str | None, default: int | None) -> int | None:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"none", "unlimited"}:
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("Integer configuration values must be greater than zero")
    return parsed


def parse_positive_float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("Float configuration values must be greater than zero")
    return parsed


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def load_settings() -> SimulatorSettings:
    return SimulatorSettings(
        interval_seconds=parse_positive_float(os.getenv("SIMULATOR_INTERVAL_SECONDS"), DEFAULT_INTERVAL_SECONDS),
        bp_interval_seconds=parse_optional_positive_int(os.getenv("SIMULATOR_BP_INTERVAL_SECONDS"), DEFAULT_BP_INTERVAL_SECONDS) or DEFAULT_BP_INTERVAL_SECONDS,
        max_cycles=parse_optional_positive_int(os.getenv("SIMULATOR_MAX_CYCLES"), DEFAULT_MAX_CYCLES),
        replay=parse_bool(os.getenv("SIMULATOR_REPLAY"), False),
        publish_max_attempts=parse_optional_positive_int(
            os.getenv("SIMULATOR_PUBLISH_MAX_ATTEMPTS"), DEFAULT_PUBLISH_MAX_ATTEMPTS
        )
        or DEFAULT_PUBLISH_MAX_ATTEMPTS,
        publish_retry_backoff_seconds=parse_positive_float(
            os.getenv("SIMULATOR_PUBLISH_RETRY_BACKOFF_SECONDS"), DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS
        ),
        max_consecutive_failed_cycles=parse_optional_positive_int(
            os.getenv("SIMULATOR_MAX_CONSECUTIVE_FAILED_CYCLES"), DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES
        )
        or DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES,
    )


def handle_shutdown(signum: int, frame: object) -> None:
    del frame
    print()
    print(f"Shutdown signal received: {signal.Signals(signum).name}")
    shutdown_event.set()


def register_signal_handlers() -> None:
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)


def load_patient_simulations(bp_interval_seconds: int) -> list[PatientSimulation]:
    cohort = get_patient_cohort(expected_count=COHORT_SIZE)
    bp_readings = load_synthea_blood_pressure_readings()
    simulations = []
    for bidmc_record_number, context in enumerate(cohort, start=1):
        readings = fetch_remote_bidmc_record(bidmc_record_number)
        if not readings:
            raise RuntimeError(f"BIDMC record {bidmc_record_number} contains no readings")
        patient_bp_readings = readings_for_patient(bp_readings, context.synthea_patient_id)
        simulations.append(
            PatientSimulation(
                context=context,
                bidmc_record_number=bidmc_record_number,
                readings=readings,
                bp_cadence=BloodPressureCadence(readings=patient_bp_readings, interval_seconds=bp_interval_seconds),
            )
        )
    return simulations


def get_available_cycle_count(simulations: list[PatientSimulation]) -> int:
    if not simulations:
        raise RuntimeError("Patient simulation cohort is empty")
    return min(len(simulation.readings) for simulation in simulations)


def get_replay_reading(reading: VitalReading, replay_index: int, available_cycles: int) -> VitalReading:
    replay_offset = replay_index * available_cycles
    return replace(reading, offset_seconds=reading.offset_seconds + replay_offset)


def get_cycle_simulation_start(cycle_timestamp: datetime, reading: VitalReading) -> datetime:
    return cycle_timestamp - timedelta(seconds=reading.offset_seconds)


def publish_patient_cycle(
    simulation: PatientSimulation,
    cycle_index: int,
    replay_index: int,
    available_cycles: int,
    cycle_timestamp: datetime,
    publish_max_attempts: int = DEFAULT_PUBLISH_MAX_ATTEMPTS,
    publish_retry_backoff_seconds: float = DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS,
) -> PublishedSimulatorEvent:
    source_reading = simulation.readings[cycle_index]
    reading = get_replay_reading(source_reading, replay_index, available_cycles)
    simulation_start = get_cycle_simulation_start(cycle_timestamp, reading)
    event = build_simulator_event(
        reading=reading,
        patient_id=simulation.context.hapi_patient_id,
        encounter_id=simulation.context.hapi_encounter_id,
        simulation_start=simulation_start,
        bp_cadence=simulation.bp_cadence,
    )
    for attempt in range(1, publish_max_attempts + 1):
        try:
            return publish_simulator_event(event, HAPIFHIRClient())
        except FHIRRetryableError as error:
            if attempt == publish_max_attempts:
                raise
            delay_seconds = publish_retry_backoff_seconds * (2 ** (attempt - 1))
            print(
                "patient_publish_retry "
                f"patient_id={simulation.context.hapi_patient_id} "
                f"attempt={attempt}/{publish_max_attempts} "
                f"delay_seconds={delay_seconds:g} "
                f"error={str(error)!r}"
            )
            if shutdown_event.wait(timeout=delay_seconds):
                raise FHIRRetryableError("Patient publication interrupted by shutdown") from error

    raise RuntimeError("Patient publication ended without a result")


def run_cycle(
    executor: ThreadPoolExecutor,
    simulations: list[PatientSimulation],
    cycle_index: int,
    replay_index: int,
    available_cycles: int,
    cycle_timestamp: datetime,
    publish_max_attempts: int = DEFAULT_PUBLISH_MAX_ATTEMPTS,
    publish_retry_backoff_seconds: float = DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS,
) -> CyclePublishResult:
    futures = {
        executor.submit(
            publish_patient_cycle,
            simulation,
            cycle_index,
            replay_index,
            available_cycles,
            cycle_timestamp,
            publish_max_attempts,
            publish_retry_backoff_seconds,
        ): simulation
        for simulation in simulations
    }
    published_count = 0
    observation_count = 0
    failures = []
    for future in as_completed(futures):
        simulation = futures[future]
        try:
            published = future.result()
        except Exception as error:
            failure = PatientCycleFailure(
                patient_id=simulation.context.hapi_patient_id,
                bidmc_record_number=simulation.bidmc_record_number,
                error_type=type(error).__name__,
                error_message=str(error).replace("\n", " "),
                retryable=isinstance(error, FHIRRetryableError),
            )
            failures.append(failure)
            print(
                "patient_publish_failed "
                f"patient_id={failure.patient_id} "
                f"bidmc_record={failure.bidmc_record_number} "
                f"retryable={str(failure.retryable).lower()} "
                f"error_type={failure.error_type} "
                f"error={failure.error_message!r}"
            )
            continue
        published_count += 1
        observation_count += published.published_count
    return CyclePublishResult(
        published_count=published_count,
        observation_count=observation_count,
        failures=tuple(sorted(failures, key=lambda failure: failure.patient_id)),
    )


def wait_for_next_cycle(cycle_started: float, interval_seconds: float) -> None:
    elapsed = time.monotonic() - cycle_started
    sleep_seconds = max(0.0, interval_seconds - elapsed)
    shutdown_event.wait(timeout=sleep_seconds)


def run_realtime_cohort(settings: SimulatorSettings | None = None) -> int:
    settings = settings or load_settings()
    shutdown_event.clear()
    simulations = load_patient_simulations(settings.bp_interval_seconds)
    available_cycles = get_available_cycle_count(simulations)
    total_published_events = 0
    completed_cycles = 0
    consecutive_failed_cycles = 0
    print("Healthcare Realtime Persistent Cohort")
    print(f"Patients: {len(simulations)}")
    print(f"Available BIDMC cycles: {available_cycles}")
    print(f"Cycle interval: {settings.interval_seconds} seconds")
    print(f"BP interval: {settings.bp_interval_seconds} seconds")
    print(f"Maximum cycles: {settings.max_cycles if settings.max_cycles is not None else 'unlimited'}")
    print(f"Replay: {settings.replay}")
    print(f"Publish attempts: {settings.publish_max_attempts}")
    print(f"Publish retry backoff: {settings.publish_retry_backoff_seconds} seconds")
    print(f"Maximum consecutive degraded cycles: {settings.max_consecutive_failed_cycles}")
    print()
    with ThreadPoolExecutor(max_workers=COHORT_SIZE) as executor:
        while not shutdown_event.is_set():
            if settings.max_cycles is not None and completed_cycles >= settings.max_cycles:
                break
            source_cycle_index = completed_cycles % available_cycles
            replay_index = completed_cycles // available_cycles
            if replay_index > 0 and source_cycle_index == 0:
                if not settings.replay:
                    break
                print(f"Starting replay epoch {replay_index + 1}.")
            cycle_started = time.monotonic()
            cycle_timestamp = utc_now()
            cycle_result = run_cycle(
                executor=executor,
                simulations=simulations,
                cycle_index=source_cycle_index,
                replay_index=replay_index,
                available_cycles=available_cycles,
                cycle_timestamp=cycle_timestamp,
                publish_max_attempts=settings.publish_max_attempts,
                publish_retry_backoff_seconds=settings.publish_retry_backoff_seconds,
            )
            if cycle_result.failures:
                consecutive_failed_cycles += 1
            else:
                consecutive_failed_cycles = 0
            total_published_events += cycle_result.published_count
            completed_cycles += 1
            source_offset = simulations[0].readings[source_cycle_index].offset_seconds
            replay_offset = replay_index * available_cycles
            effective_offset = source_offset + replay_offset
            print(
                f"cycle={completed_cycles} "
                f"status={'degraded' if cycle_result.failures else 'healthy'} "
                f"replay_epoch={replay_index + 1} "
                f"source_cycle={source_cycle_index + 1}/{available_cycles} "
                f"offset={effective_offset}s "
                f"patients_succeeded={cycle_result.published_count} "
                f"patients_failed={len(cycle_result.failures)} "
                f"observations={cycle_result.observation_count} "
                f"failed_patient_ids={','.join(failure.patient_id for failure in cycle_result.failures) or 'none'} "
                f"consecutive_failed_cycles={consecutive_failed_cycles}"
            )
            if consecutive_failed_cycles >= settings.max_consecutive_failed_cycles:
                raise RuntimeError(
                    "Simulator stopped after "
                    f"{consecutive_failed_cycles} consecutive degraded cycles "
                    f"(threshold={settings.max_consecutive_failed_cycles})"
                )
            if shutdown_event.is_set():
                break
            wait_for_next_cycle(cycle_started, settings.interval_seconds)
    print()
    print(f"Simulation stopped. Completed cycles: {completed_cycles}")
    print(f"Published patient events: {total_published_events}")
    return total_published_events


def main() -> None:
    register_signal_handlers()
    run_realtime_cohort()


if __name__ == "__main__":
    main()
