from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from services.vitals_simulator.app.bidmc.source import fetch_remote_bidmc_record
from services.vitals_simulator.app.fhir.client import HAPIFHIRClient
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext, get_patient_cohort
from services.vitals_simulator.app.fhir.observation import utc_now
from services.vitals_simulator.app.fhir.publisher import PublishedSimulatorEvent, publish_simulator_event
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.synthea.blood_pressure import load_synthea_blood_pressure_readings
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence

COHORT_SIZE = 10
DEFAULT_BP_INTERVAL_SECONDS = 300


def publish_patient_event(context: FHIRPatientContext, bidmc_record_number: int, simulation_start: datetime) -> PublishedSimulatorEvent:
    readings = fetch_remote_bidmc_record(bidmc_record_number)

    if not readings:
        raise RuntimeError(f"BIDMC record {bidmc_record_number} contains no readings")

    bp_readings = load_synthea_blood_pressure_readings()

    bp_cadence = BloodPressureCadence(readings=bp_readings, interval_seconds=DEFAULT_BP_INTERVAL_SECONDS)

    event = build_simulator_event(
        reading=readings[0],
        patient_id=context.hapi_patient_id,
        encounter_id=context.hapi_encounter_id,
        simulation_start=simulation_start,
        bp_cadence=bp_cadence,
    )

    client = HAPIFHIRClient()

    return publish_simulator_event(event, client)


def run_cohort_once() -> list[PublishedSimulatorEvent]:
    cohort = get_patient_cohort(expected_count=COHORT_SIZE)

    simulation_start = utc_now()

    print("Healthcare Realtime Production Cohort")
    print(f"Patients: {len(cohort)}")
    print("Events: 1 cycle per patient")
    print()

    published_events = []

    with ThreadPoolExecutor(max_workers=COHORT_SIZE) as executor:
        futures = {executor.submit(publish_patient_event, context, index, simulation_start): context for index, context in enumerate(cohort, start=1)}

        for future in as_completed(futures):
            context = futures[future]

            published = future.result()

            published_events.append(published)

            print(f"Patient/{context.hapi_patient_id} BIDMC={published.source_record_id} observations={published.published_count}")

    if len(published_events) != COHORT_SIZE:
        raise RuntimeError(f"Expected {COHORT_SIZE} published patient events but received {len(published_events)}")

    print()
    print(f"Successfully published one realtime cycle for all {COHORT_SIZE} patients.")

    return published_events


def main() -> None:
    run_cohort_once()


if __name__ == "__main__":
    main()
