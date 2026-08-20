import json

from services.vitals_simulator.app.bidmc.source import (
    fetch_remote_bidmc_record,
)
from services.vitals_simulator.app.fhir.mapping import (
    get_first_patient_and_encounter,
)
from services.vitals_simulator.app.fhir.observation import (
    build_observations_from_reading,
    utc_now,
)


def main():
    patient_id, encounter_id = (
        get_first_patient_and_encounter()
    )

    print(
        f"Patient: Patient/{patient_id}"
    )

    print(
        f"Encounter: Encounter/{encounter_id}"
    )

    readings = fetch_remote_bidmc_record(
        1
    )

    if not readings:
        raise RuntimeError(
            "No BIDMC readings returned"
        )

    simulation_start = utc_now()

    reading = readings[0]

    observations = (
        build_observations_from_reading(
            reading=reading,
            patient_id=patient_id,
            encounter_id=encounter_id,
            simulation_start=simulation_start,
        )
    )

    print(
        "\nBIDMC reading:"
    )

    print(
        json.dumps(
            reading.to_dict(),
            indent=2,
        )
    )

    print(
        f"\nGenerated "
        f"{len(observations)} "
        "FHIR Observations:"
    )

    for observation in observations:
        print()
        print(
            json.dumps(
                observation,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()