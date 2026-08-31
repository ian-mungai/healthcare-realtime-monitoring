import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from threading import Event

from services.vitals_simulator.app.bidmc.source import VitalReading, fetch_remote_bidmc_record
from services.vitals_simulator.app.fhir.client import HAPIFHIRClient
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext, get_patient_cohort
from services.vitals_simulator.app.fhir.observation import utc_now
from services.vitals_simulator.app.fhir.publisher import PublishedSimulatorEvent, publish_simulator_event
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import load_synthea_blood_pressure_readings
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence

COHORT_SIZE = 10
DEFAULT_INTERVAL_SECONDS = 1.0
DEFAULT_BP_INTERVAL_SECONDS = 300
DEFAULT_MAX_CYCLES = 10

shutdown_event = Event()


@dataclass
class SimulatorSettings:
    interval_seconds: float
    bp_interval_seconds: int
    max_cycles: int | None
    replay: bool


@dataclass
class PatientSimulation:
    context: FHIRPatientContext
    bidmc_record_number: int
    readings: list[VitalReading]
    bp_cadence: BloodPressureCadence


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
        simulations.append(
            PatientSimulation(
                context=context,
                bidmc_record_number=bidmc_record_number,
                readings=readings,
                bp_cadence=BloodPressureCadence(readings=bp_readings, interval_seconds=bp_interval_seconds),
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


def publish_patient_cycle(
    simulation: PatientSimulation, cycle_index: int, replay_index: int, available_cycles: int, simulation_start: datetime
) -> PublishedSimulatorEvent:
    source_reading = simulation.readings[cycle_index]
    reading = get_replay_reading(source_reading, replay_index, available_cycles)
    event = build_simulator_event(
        reading=reading,
        patient_id=simulation.context.hapi_patient_id,
        encounter_id=simulation.context.hapi_encounter_id,
        simulation_start=simulation_start,
        bp_cadence=simulation.bp_cadence,
    )
    return publish_simulator_event(event, HAPIFHIRClient())


def run_cycle(
    executor: ThreadPoolExecutor, simulations: list[PatientSimulation], cycle_index: int, replay_index: int, available_cycles: int, simulation_start: datetime
) -> tuple[int, int]:
    futures = {
        executor.submit(publish_patient_cycle, simulation, cycle_index, replay_index, available_cycles, simulation_start): simulation
        for simulation in simulations
    }
    published_count = 0
    observation_count = 0
    for future in as_completed(futures):
        published = future.result()
        published_count += 1
        observation_count += published.published_count
    return published_count, observation_count


def wait_for_next_cycle(cycle_started: float, interval_seconds: float) -> None:
    elapsed = time.monotonic() - cycle_started
    sleep_seconds = max(0.0, interval_seconds - elapsed)
    shutdown_event.wait(timeout=sleep_seconds)


def run_realtime_cohort(settings: SimulatorSettings | None = None) -> int:
    settings = settings or load_settings()
    shutdown_event.clear()
    simulations = load_patient_simulations(settings.bp_interval_seconds)
    available_cycles = get_available_cycle_count(simulations)
    simulation_start = utc_now()
    total_published_events = 0
    completed_cycles = 0
    print("Healthcare Realtime Persistent Cohort")
    print(f"Patients: {len(simulations)}")
    print(f"Available BIDMC cycles: {available_cycles}")
    print(f"Cycle interval: {settings.interval_seconds} seconds")
    print(f"BP interval: {settings.bp_interval_seconds} seconds")
    print(f"Maximum cycles: {settings.max_cycles if settings.max_cycles is not None else 'unlimited'}")
    print(f"Replay: {settings.replay}")
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
            published_count, observation_count = run_cycle(
                executor=executor,
                simulations=simulations,
                cycle_index=source_cycle_index,
                replay_index=replay_index,
                available_cycles=available_cycles,
                simulation_start=simulation_start,
            )
            if published_count != len(simulations):
                raise RuntimeError(f"Cycle {completed_cycles + 1} published {published_count} patient events instead of {len(simulations)}")
            total_published_events += published_count
            completed_cycles += 1
            source_offset = simulations[0].readings[source_cycle_index].offset_seconds
            replay_offset = replay_index * available_cycles
            effective_offset = source_offset + replay_offset
            print(
                f"cycle={completed_cycles} "
                f"replay_epoch={replay_index + 1} "
                f"source_cycle={source_cycle_index + 1}/{available_cycles} "
                f"offset={effective_offset}s "
                f"patients={published_count} "
                f"observations={observation_count}"
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
