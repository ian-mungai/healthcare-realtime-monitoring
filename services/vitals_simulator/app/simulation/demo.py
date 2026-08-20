import json
from pathlib import Path

from services.vitals_simulator.app.bidmc.source import fetch_remote_bidmc_record
from services.vitals_simulator.app.fhir.mapping import get_first_patient_and_encounter
from services.vitals_simulator.app.fhir.observation import utc_now
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import (
    load_synthea_blood_pressure_readings,
)
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence

OUTPUT_FILE = Path("services/vitals_simulator/output/step_6_events.json")


def main():
    patient_id, encounter_id = get_first_patient_and_encounter()
    bidmc_readings = fetch_remote_bidmc_record(1)
    bp_readings = load_synthea_blood_pressure_readings()
    bp_cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = utc_now()
    events = []

    for reading in bidmc_readings[:5]:
        event = build_simulator_event(
            reading=reading,
            patient_id=patient_id,
            encounter_id=encounter_id,
            simulation_start=simulation_start,
            bp_cadence=bp_cadence,
        )

        events.append(event.to_dict())

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(events, file, indent=2)

    print(f"Patient: Patient/{patient_id}")
    print(f"Encounter: Encounter/{encounter_id}")
    print(f"BIDMC readings available: {len(bidmc_readings)}")
    print(f"Synthea BP readings available: {len(bp_readings)}")
    print(f"BP interval: {bp_cadence.interval_seconds} seconds")
    print(f"Events written: {len(events)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()