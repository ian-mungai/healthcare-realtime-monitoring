import logging
import os
import signal
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import Event

from services.vitals_simulator.app.bidmc.source import (
    VitalReading,
    bidmc_source_for_position,
    fetch_remote_bidmc_record,
    rotate_readings,
    vary_reused_readings,
    vary_run_readings,
)
from services.vitals_simulator.app.fhir.admission import plan_admission
from services.vitals_simulator.app.fhir.client import FHIRRetryableError, HAPIFHIRClient
from services.vitals_simulator.app.fhir.encounter import SIMULATOR_SCENARIO_TAG_SYSTEM, build_simulator_encounter
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext, get_patient_cohort
from services.vitals_simulator.app.fhir.observation import utc_now
from services.vitals_simulator.app.fhir.publisher import PublishedSimulatorEvent, publish_simulator_event
from services.vitals_simulator.app.simulation.bedside import BASELINE_MEAN, BedsideCadence, baseline_temperature
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.simulation.precursor import (
    NO_PRECURSOR,
    Precursor,
    apply_precursor_to_vitals,
    is_65_plus,
    load_planted_signal,
    sample_precursor,
)
from services.vitals_simulator.app.simulation.scenario import LABEL_WINDOW_SECONDS, NORMAL_SCENARIO, SCENARIOS, apply_vital_scenario, choose_patient_scenarios
from services.vitals_simulator.app.synthea.blood_pressure import load_synthea_blood_pressure_readings, readings_for_patient
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence


class _CurrentStdoutHandler(logging.Handler):
    """Write each record to the current sys.stdout, where CloudWatch collects this runtime's output."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(f"{self.format(record)}\n")
        except (OSError, ValueError):
            self.handleError(record)


LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    _handler = _CurrentStdoutHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False

DEFAULT_INTERVAL_SECONDS = 1.0
DEFAULT_BP_INTERVAL_SECONDS = 300
DEFAULT_MAX_CYCLES = 10
DEFAULT_PUBLISH_MAX_ATTEMPTS = 2
DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES = 3
DEFAULT_FAILURE_RATIO_THRESHOLD = 0.5

shutdown_event = Event()


@dataclass
class SimulatorSettings:
    interval_seconds: float
    bp_interval_seconds: int
    max_cycles: int | None
    replay: bool
    fhir_max_attempts: int = DEFAULT_PUBLISH_MAX_ATTEMPTS
    fhir_retry_backoff_seconds: float = DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS
    max_consecutive_failed_cycles: int = DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES
    failure_ratio_threshold: float = DEFAULT_FAILURE_RATIO_THRESHOLD
    scenario_seed: str | None = None


@dataclass
class PatientSimulation:
    context: FHIRPatientContext
    bidmc_record_number: int
    readings: list[VitalReading]
    bp_cadence: BloodPressureCadence
    scenario: str = NORMAL_SCENARIO
    baseline_temperature: float = BASELINE_MEAN
    # Set per run by initialize_simulation_run, seeded by the scenario seed, the patient and the run.
    bedside_cadence: BedsideCadence | None = None
    precursor: Precursor = NO_PRECURSOR


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


def parse_ratio(value: str | None, default: float) -> float:
    parsed = parse_positive_float(value, default)
    if parsed > 1:
        raise ValueError("Ratio configuration values must be less than or equal to one")
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
        fhir_max_attempts=parse_optional_positive_int(
            os.getenv("SIMULATOR_FHIR_MAX_ATTEMPTS") or os.getenv("SIMULATOR_PUBLISH_MAX_ATTEMPTS"), DEFAULT_PUBLISH_MAX_ATTEMPTS
        )
        or DEFAULT_PUBLISH_MAX_ATTEMPTS,
        fhir_retry_backoff_seconds=parse_positive_float(
            os.getenv("SIMULATOR_FHIR_RETRY_BACKOFF_SECONDS") or os.getenv("SIMULATOR_PUBLISH_RETRY_BACKOFF_SECONDS"), DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS
        ),
        max_consecutive_failed_cycles=parse_optional_positive_int(os.getenv("SIMULATOR_MAX_CONSECUTIVE_FAILED_CYCLES"), DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES)
        or DEFAULT_MAX_CONSECUTIVE_FAILED_CYCLES,
        failure_ratio_threshold=parse_ratio(os.getenv("SIMULATOR_FAILURE_RATIO_THRESHOLD"), DEFAULT_FAILURE_RATIO_THRESHOLD),
        scenario_seed=os.getenv("SIMULATOR_SCENARIO_SEED") or None,
    )


def handle_shutdown(signum: int, frame: object) -> None:
    del frame
    LOGGER.info("")
    LOGGER.info(f"Shutdown signal received: {signal.Signals(signum).name}")
    shutdown_event.set()


def register_signal_handlers() -> None:
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)


def load_patient_simulations(bp_interval_seconds: int) -> list[PatientSimulation]:
    cohort = get_patient_cohort()
    bp_readings = load_synthea_blood_pressure_readings()
    simulations = []
    records: dict[int, list[VitalReading]] = {}
    for position, context in enumerate(cohort, start=1):
        bidmc_record_number, epoch = bidmc_source_for_position(position)
        if bidmc_record_number not in records:
            records[bidmc_record_number] = fetch_remote_bidmc_record(bidmc_record_number)
        if not records[bidmc_record_number]:
            raise RuntimeError(f"BIDMC record {bidmc_record_number} contains no readings")
        readings = vary_reused_readings(rotate_readings(records[bidmc_record_number], epoch), bidmc_record_number, epoch)
        patient_bp_readings = readings_for_patient(bp_readings, context.synthea_patient_id)
        simulations.append(
            PatientSimulation(
                context=context,
                bidmc_record_number=bidmc_record_number,
                readings=readings,
                bp_cadence=BloodPressureCadence(readings=patient_bp_readings, interval_seconds=bp_interval_seconds),
                baseline_temperature=baseline_temperature(context.synthea_patient_id),
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


def is_label_eligible(settings: SimulatorSettings, available_cycles: int) -> bool:
    """Whether the run lasts a full feature and outcome window, so its encounters can produce outcome labels."""
    planned_cycles = settings.max_cycles if settings.max_cycles is not None else float("inf")
    if not settings.replay:
        planned_cycles = min(planned_cycles, available_cycles)
    return planned_cycles * settings.interval_seconds >= LABEL_WINDOW_SECONDS


def count_labelled_runs(client: HAPIFHIRClient, patient_ids: list[str]) -> dict[str, dict[str, int]]:
    """Count each patient's earlier labelled simulator encounters per scenario, from their HAPI scenario tags."""
    return {
        patient_id: {
            scenario: client.count_resources("Encounter", {"subject": f"Patient/{patient_id}", "_tag": f"{SIMULATOR_SCENARIO_TAG_SYSTEM}|{scenario}"})
            for scenario in SCENARIOS
        }
        for patient_id in patient_ids
    }


def initialize_simulation_run(
    simulations: list[PatientSimulation],
    started_at: datetime,
    seed: str | int | None = None,
    client: HAPIFHIRClient | None = None,
    run_id: str | None = None,
    label_eligible: bool = False,
) -> tuple[str, list[PatientSimulation]]:
    run_id = run_id or uuid.uuid4().hex
    client = client or HAPIFHIRClient()
    patient_ids = [simulation.context.hapi_patient_id for simulation in simulations]
    # Only runs long enough to produce labels count and are tagged; short check runs would otherwise skew the balance.
    prior_counts = count_labelled_runs(client, patient_ids) if label_eligible else None
    scenarios = choose_patient_scenarios(patient_ids, seed, prior_counts)
    # The planted early-warning trend of the study (config/planted_signal.json); null_control plants nothing.
    planted_signal = load_planted_signal(os.getenv("SIMULATOR_PLANTED_SIGNAL") or "study")
    initialized = []
    for simulation in simulations:
        patient_id = simulation.context.hapi_patient_id
        tag = scenarios[patient_id] if label_eligible else None
        admission = plan_admission(simulation.context.admission_profile, seed, patient_id, run_id)
        created = client.post_resource(build_simulator_encounter(patient_id, run_id, started_at, scenario=tag, admission=admission))
        context = replace(simulation.context, hapi_encounter_id=created.resource_id)
        interval_seconds = simulation.bp_cadence.interval_seconds if simulation.bp_cadence is not None else DEFAULT_BP_INTERVAL_SECONDS
        bedside = BedsideCadence(
            baseline_temperature=simulation.baseline_temperature, seed_key=f"{seed}:{patient_id}:{run_id}", interval_seconds=interval_seconds
        )
        birth_date = (simulation.context.admission_profile or {}).get("birth_date")
        # A map written before birth dates were recorded puts the patient in the under-65 group.
        older = isinstance(birth_date, str) and bool(birth_date) and is_65_plus(birth_date, started_at)
        precursor = sample_precursor(planted_signal, scenarios[patient_id], seed, patient_id, run_id, older)
        # Each run gets its own stretch of the patient's record and its own small offsets, so runs do not copy each other.
        readings = vary_run_readings(simulation.readings, f"{seed}:{patient_id}:{run_id}")
        initialized.append(
            replace(simulation, context=context, readings=readings, scenario=scenarios[patient_id], bedside_cadence=bedside, precursor=precursor)
        )
    return run_id, initialized


def publish_patient_cycle(
    simulation: PatientSimulation,
    cycle_index: int,
    replay_index: int,
    available_cycles: int,
    cycle_timestamp: datetime,
    fhir_max_attempts: int = DEFAULT_PUBLISH_MAX_ATTEMPTS,
    fhir_retry_backoff_seconds: float = DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS,
    bp_elapsed_seconds: float | None = None,
) -> PublishedSimulatorEvent:
    source_reading = simulation.readings[cycle_index]
    reading = get_replay_reading(source_reading, replay_index, available_cycles)
    scenario_elapsed_seconds = reading.offset_seconds if bp_elapsed_seconds is None else bp_elapsed_seconds
    reading = apply_precursor_to_vitals(reading, simulation.precursor, scenario_elapsed_seconds)
    reading = apply_vital_scenario(reading, simulation.scenario, scenario_elapsed_seconds)
    simulation_start = get_cycle_simulation_start(cycle_timestamp, reading)
    event = build_simulator_event(
        reading=reading,
        patient_id=simulation.context.hapi_patient_id,
        encounter_id=simulation.context.hapi_encounter_id,
        simulation_start=simulation_start,
        bp_cadence=simulation.bp_cadence,
        bp_elapsed_seconds=bp_elapsed_seconds,
        scenario=simulation.scenario,
        bedside_cadence=simulation.bedside_cadence,
        precursor=simulation.precursor,
    )
    client = HAPIFHIRClient(max_retries=fhir_max_attempts, retry_delay_seconds=fhir_retry_backoff_seconds)
    return publish_simulator_event(event, client)


def run_cycle(
    executor: ThreadPoolExecutor,
    simulations: list[PatientSimulation],
    cycle_index: int,
    replay_index: int,
    available_cycles: int,
    cycle_timestamp: datetime,
    fhir_max_attempts: int = DEFAULT_PUBLISH_MAX_ATTEMPTS,
    fhir_retry_backoff_seconds: float = DEFAULT_PUBLISH_RETRY_BACKOFF_SECONDS,
    bp_elapsed_seconds: float | None = None,
) -> CyclePublishResult:
    futures = {
        executor.submit(
            publish_patient_cycle,
            simulation,
            cycle_index,
            replay_index,
            available_cycles,
            cycle_timestamp,
            fhir_max_attempts,
            fhir_retry_backoff_seconds,
            bp_elapsed_seconds,
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
            LOGGER.warning(
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
        published_count=published_count, observation_count=observation_count, failures=tuple(sorted(failures, key=lambda failure: failure.patient_id))
    )


def wait_for_next_cycle(cycle_started: float, interval_seconds: float) -> float:
    elapsed = time.monotonic() - cycle_started
    overrun_seconds = max(0.0, elapsed - interval_seconds)
    if overrun_seconds:
        LOGGER.warning(f"cycle_overrun overrun_seconds={overrun_seconds:.3f} elapsed_seconds={elapsed:.3f} interval_seconds={interval_seconds:g}")
    sleep_seconds = max(0.0, interval_seconds - elapsed)
    shutdown_event.wait(timeout=sleep_seconds)
    return overrun_seconds


def run_realtime_cohort(settings: SimulatorSettings | None = None) -> int:
    settings = settings or load_settings()
    shutdown_event.clear()
    simulations = load_patient_simulations(settings.bp_interval_seconds)
    run_started_at = utc_now()
    available_cycles = get_available_cycle_count(simulations)
    label_eligible = is_label_eligible(settings, available_cycles)
    run_id, simulations = initialize_simulation_run(
        simulations,
        started_at=run_started_at,
        seed=settings.scenario_seed,
        client=HAPIFHIRClient(max_retries=settings.fhir_max_attempts, retry_delay_seconds=settings.fhir_retry_backoff_seconds),
        label_eligible=label_eligible,
    )
    total_published_events = 0
    completed_cycles = 0
    consecutive_failed_cycles = 0
    disabled_patient_ids: set[str] = set()
    LOGGER.info("Healthcare Realtime Persistent Cohort")
    LOGGER.info(f"Patients: {len(simulations)}")
    LOGGER.info(f"Available BIDMC cycles: {available_cycles}")
    LOGGER.info(f"Cycle interval: {settings.interval_seconds} seconds")
    LOGGER.info(f"BP interval: {settings.bp_interval_seconds} seconds")
    LOGGER.info(f"Maximum cycles: {settings.max_cycles if settings.max_cycles is not None else 'unlimited'}")
    LOGGER.info(f"Replay: {settings.replay}")
    LOGGER.info(f"FHIR attempts: {settings.fhir_max_attempts}")
    LOGGER.info(f"FHIR retry backoff: {settings.fhir_retry_backoff_seconds} seconds")
    LOGGER.warning(f"Maximum consecutive degraded cycles: {settings.max_consecutive_failed_cycles}")
    LOGGER.warning(f"Retryable failure ratio threshold: {settings.failure_ratio_threshold:g}")
    LOGGER.info(f"Simulation run ID: {run_id}")
    LOGGER.info(f"Scenario seed: {settings.scenario_seed or 'random'}")
    LOGGER.info(f"Label-eligible run (scenarios balanced per patient): {label_eligible}")
    for simulation in simulations:
        LOGGER.info(
            "scenario_assigned "
            f"patient_id={simulation.context.hapi_patient_id} "
            f"encounter_id={simulation.context.hapi_encounter_id} "
            f"scenario={simulation.scenario}"
        )
    LOGGER.info("")
    with ThreadPoolExecutor(max_workers=len(simulations)) as executor:
        while not shutdown_event.is_set():
            if settings.max_cycles is not None and completed_cycles >= settings.max_cycles:
                break
            source_cycle_index = completed_cycles % available_cycles
            replay_index = completed_cycles // available_cycles
            if replay_index > 0 and source_cycle_index == 0:
                if not settings.replay:
                    break
                LOGGER.info(f"Starting replay epoch {replay_index + 1}.")
            active_simulations = [simulation for simulation in simulations if simulation.context.hapi_patient_id not in disabled_patient_ids]
            if not active_simulations:
                raise RuntimeError("Simulator stopped because no active patients remain")
            cycle_started = time.monotonic()
            cycle_timestamp = utc_now()
            cycle_result = run_cycle(
                executor=executor,
                simulations=active_simulations,
                cycle_index=source_cycle_index,
                replay_index=replay_index,
                available_cycles=available_cycles,
                cycle_timestamp=cycle_timestamp,
                fhir_max_attempts=settings.fhir_max_attempts,
                fhir_retry_backoff_seconds=settings.fhir_retry_backoff_seconds,
                bp_elapsed_seconds=completed_cycles * settings.interval_seconds,
            )
            permanent_failures = [failure for failure in cycle_result.failures if not failure.retryable]
            for failure in permanent_failures:
                disabled_patient_ids.add(failure.patient_id)
                LOGGER.warning(f"patient_disabled patient_id={failure.patient_id} bidmc_record={failure.bidmc_record_number} reason={failure.error_type}")
            retryable_failure_count = sum(failure.retryable for failure in cycle_result.failures)
            retryable_failure_ratio = retryable_failure_count / len(active_simulations)
            if retryable_failure_ratio >= settings.failure_ratio_threshold:
                consecutive_failed_cycles += 1
            else:
                consecutive_failed_cycles = 0
            total_published_events += cycle_result.published_count
            completed_cycles += 1
            source_offset = simulations[0].readings[source_cycle_index].offset_seconds
            replay_offset = replay_index * available_cycles
            effective_offset = source_offset + replay_offset
            LOGGER.warning(
                f"cycle={completed_cycles} "
                f"status={'degraded' if cycle_result.failures else 'healthy'} "
                f"replay_epoch={replay_index + 1} "
                f"source_cycle={source_cycle_index + 1}/{available_cycles} "
                f"offset={effective_offset}s "
                f"patients_succeeded={cycle_result.published_count} "
                f"patients_failed={len(cycle_result.failures)} "
                f"patients_disabled={len(disabled_patient_ids)} "
                f"retryable_failure_ratio={retryable_failure_ratio:.3f} "
                f"observations={cycle_result.observation_count} "
                f"failed_patient_ids={','.join(failure.patient_id for failure in cycle_result.failures) or 'none'} "
                f"consecutive_failed_cycles={consecutive_failed_cycles}"
            )
            if consecutive_failed_cycles >= settings.max_consecutive_failed_cycles:
                raise RuntimeError(
                    f"Simulator stopped after {consecutive_failed_cycles} consecutive systemic failure cycles "
                    f"(ratio_threshold={settings.failure_ratio_threshold:g})"
                )
            if shutdown_event.is_set():
                break
            wait_for_next_cycle(cycle_started, settings.interval_seconds)
    LOGGER.info("")
    LOGGER.info(f"Simulation stopped. Completed cycles: {completed_cycles}")
    LOGGER.info(f"Published patient events: {total_published_events}")
    return total_published_events


def main() -> None:
    register_signal_handlers()
    run_realtime_cohort()


if __name__ == "__main__":
    main()
