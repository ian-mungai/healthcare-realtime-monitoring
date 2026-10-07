from datetime import datetime

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.fhir.identifier import add_observation_identifier
from services.vitals_simulator.app.fhir.observation import (
    build_bedside_observations,
    build_blood_pressure_observation,
    build_effective_datetime,
    build_observations_from_reading,
)
from services.vitals_simulator.app.simulation.bedside import BedsideCadence
from services.vitals_simulator.app.simulation.event import SimulatorEvent
from services.vitals_simulator.app.simulation.precursor import NO_PRECURSOR, Precursor, apply_precursor_to_bedside, apply_precursor_to_blood_pressure
from services.vitals_simulator.app.simulation.scenario import NORMAL_SCENARIO, apply_bedside_scenario, apply_blood_pressure_scenario
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence


def build_simulator_event(
    reading: VitalReading,
    patient_id: str,
    encounter_id: str,
    simulation_start: datetime,
    bp_cadence: BloodPressureCadence,
    bp_elapsed_seconds: float | None = None,
    scenario: str = NORMAL_SCENARIO,
    bedside_cadence: BedsideCadence | None = None,
    precursor: Precursor = NO_PRECURSOR,
) -> SimulatorEvent:
    observations = build_observations_from_reading(reading=reading, patient_id=patient_id, encounter_id=encounter_id, simulation_start=simulation_start)

    bp_reading = bp_cadence.get_reading(reading.offset_seconds if bp_elapsed_seconds is None else bp_elapsed_seconds)

    if bp_reading is not None:
        scenario_elapsed_seconds = reading.offset_seconds if bp_elapsed_seconds is None else bp_elapsed_seconds
        bp_reading = apply_precursor_to_blood_pressure(bp_reading, precursor, scenario_elapsed_seconds)
        bp_reading = apply_blood_pressure_scenario(bp_reading, scenario, scenario_elapsed_seconds)
        effective_datetime = build_effective_datetime(simulation_start, reading.offset_seconds)

        observations.append(
            build_blood_pressure_observation(
                patient_id=patient_id,
                encounter_id=encounter_id,
                effective_datetime=effective_datetime,
                reading=bp_reading,
                source_offset_seconds=reading.offset_seconds,
            )
        )

    elapsed_seconds = reading.offset_seconds if bp_elapsed_seconds is None else bp_elapsed_seconds
    bedside_reading = bedside_cadence.get_reading(elapsed_seconds) if bedside_cadence is not None else None

    if bedside_reading is not None:
        observations.extend(
            build_bedside_observations(
                reading=apply_bedside_scenario(apply_precursor_to_bedside(bedside_reading, precursor, elapsed_seconds), scenario, elapsed_seconds),
                patient_id=patient_id,
                encounter_id=encounter_id,
                effective_datetime=build_effective_datetime(simulation_start, reading.offset_seconds),
                source_record_id=reading.source_record_id,
                source_offset_seconds=reading.offset_seconds,
            )
        )

    for observation in observations:
        add_observation_identifier(observation=observation, source_record_id=reading.source_record_id, offset_seconds=reading.offset_seconds)

    return SimulatorEvent(
        source_record_id=reading.source_record_id,
        offset_seconds=reading.offset_seconds,
        patient_id=patient_id,
        encounter_id=encounter_id,
        observation_count=len(observations),
        observations=observations,
    )
