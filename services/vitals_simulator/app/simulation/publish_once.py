import json
from pathlib import Path

from services.vitals_simulator.app.bidmc.source import fetch_remote_bidmc_record
from services.vitals_simulator.app.fhir.client import HAPIFHIRClient
from services.vitals_simulator.app.fhir.mapping import get_first_patient_and_encounter
from services.vitals_simulator.app.fhir.observation import utc_now
from services.vitals_simulator.app.fhir.publisher import publish_simulator_event
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import load_synthea_blood_pressure_readings
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence

OUTPUT_FILE = Path("services/vitals_simulator/output/step_7_publish_once.json")


def main():
    patient_id, encounter_id = get_first_patient_and_encounter()
    bidmc_readings = fetch_remote_bidmc_record(1)
    bp_readings = load_synthea_blood_pressure_readings()
    bp_cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=300)
    simulation_start = utc_now()
    client = HAPIFHIRClient()

    reading = bidmc_readings[0]

    event = build_simulator_event(
        reading=reading,
        patient_id=patient_id,
        encounter_id=encounter_id,
        simulation_start=simulation_start,
        bp_cadence=bp_cadence,
    )

    print(f"Patient: Patient/{patient_id}")
    print(f"Encounter: Encounter/{encounter_id}")
    print(f"Offset: {reading.offset_seconds}")
    print(f"Observations to publish: {event.observation_count}")
    print("Publishing to HAPI FHIR...")

    result = publish_simulator_event(event, client)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(result.to_dict(), file, indent=2)

    print(f"Published: {result.published_count}")

    for resource in result.resources:
        print(f"Created: {resource.resource_type}/{resource.resource_id}")

    print(f"Result written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()