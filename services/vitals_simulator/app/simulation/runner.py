import json
import time
from pathlib import Path

from services.vitals_simulator.app.bidmc.source import fetch_remote_bidmc_record
from services.vitals_simulator.app.fhir.client import HAPIFHIRClient
from services.vitals_simulator.app.fhir.mapping import get_first_patient_and_encounter
from services.vitals_simulator.app.fhir.observation import utc_now
from services.vitals_simulator.app.fhir.publisher import publish_simulator_event
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import load_synthea_blood_pressure_readings
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence

DEFAULT_INTERVAL_SECONDS = 1.0
DEFAULT_BP_INTERVAL_SECONDS = 300
DEFAULT_MAX_EVENTS = 10
OUTPUT_FILE = Path("services/vitals_simulator/output/step_7_simulation.json")


def run_simulation(record_number: int = 1, interval_seconds: float = DEFAULT_INTERVAL_SECONDS, bp_interval_seconds: int = DEFAULT_BP_INTERVAL_SECONDS, max_events: int | None = DEFAULT_MAX_EVENTS):
    patient_id, encounter_id = get_first_patient_and_encounter()
    bidmc_readings = fetch_remote_bidmc_record(record_number)
    bp_readings = load_synthea_blood_pressure_readings()
    bp_cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=bp_interval_seconds)
    simulation_start = utc_now()
    client = HAPIFHIRClient()
    published_events = []

    selected_readings = bidmc_readings if max_events is None else bidmc_readings[:max_events]

    print(f"Patient: Patient/{patient_id}")
    print(f"Encounter: Encounter/{encounter_id}")
    print(f"BIDMC record: {record_number}")
    print(f"Events: {len(selected_readings)}")
    print(f"Event interval: {interval_seconds} seconds")
    print(f"BP interval: {bp_interval_seconds} seconds")
    print()

    for index, reading in enumerate(selected_readings):
        cycle_started = time.monotonic()

        event = build_simulator_event(
            reading=reading,
            patient_id=patient_id,
            encounter_id=encounter_id,
            simulation_start=simulation_start,
            bp_cadence=bp_cadence,
        )

        published = publish_simulator_event(event, client)
        published_events.append(published.to_dict())

        resource_ids = ", ".join(resource.resource_id for resource in published.resources)

        print(f"offset={reading.offset_seconds} observations={published.published_count} ids={resource_ids}")

        if index == len(selected_readings) - 1:
            continue

        elapsed = time.monotonic() - cycle_started
        sleep_seconds = max(0.0, interval_seconds - elapsed)

        time.sleep(sleep_seconds)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(published_events, file, indent=2)

    print()
    print(f"Simulation complete. Published events: {len(published_events)}")
    print(f"Results: {OUTPUT_FILE}")


def main():
    run_simulation()


if __name__ == "__main__":
    main()
    