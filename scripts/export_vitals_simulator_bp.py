import json
from pathlib import Path

from scripts.synthea_loader.src.load_fhir import find_patient_bundles, load_bundle
from services.vitals_simulator.app.synthea.blood_pressure import extract_blood_pressure_readings

OUTPUT_PATH = Path("services/vitals_simulator/data/blood_pressure_readings.json")


def main() -> None:
    patient_bundles = find_patient_bundles()
    if not patient_bundles:
        raise RuntimeError("No Synthea patient bundles found")
    readings = []
    for bundle_path in patient_bundles:
        bundle = load_bundle(bundle_path)
        readings.extend(extract_blood_pressure_readings(bundle))
    if not readings:
        raise RuntimeError("No complete Synthea blood pressure observations found")
    output = [
        {
            "source_patient_id": reading.source_patient_id,
            "source_observation_id": reading.source_observation_id,
            "systolic": reading.systolic,
            "diastolic": reading.diastolic,
        }
        for reading in readings
    ]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)
    print(f"Exported {len(output)} blood pressure readings")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
