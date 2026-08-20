from datetime import datetime

from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.fhir.observation import (
    build_blood_pressure_observation,
    build_effective_datetime,
    build_observations_from_reading,
)
from services.vitals_simulator.app.simulation.event import SimulatorEvent
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence


def build_simulator_event(reading: VitalReading, patient_id: str, encounter_id: str, simulation_start: datetime, bp_cadence: BloodPressureCadence) -> SimulatorEvent:
    observations = build_observations_from_reading(
        reading=reading,
        patient_id=patient_id,
        encounter_id=encounter_id,
        simulation_start=simulation_start,
    )

    bp_reading = bp_cadence.get_reading(reading.offset_seconds)

    if bp_reading is not None:
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

    return SimulatorEvent(
        source_record_id=reading.source_record_id,
        offset_seconds=reading.offset_seconds,
        patient_id=patient_id,
        encounter_id=encounter_id,
        observation_count=len(observations),
        observations=observations,
    )