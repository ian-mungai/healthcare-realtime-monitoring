import json
from pathlib import Path

OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "synthea"
    / "output"
    / "fhir"
)


def load_fhir_bundles():
    bundles = []

    if not OUTPUT_DIR.exists():
        return bundles

    for file_path in OUTPUT_DIR.glob("*.json"):
        with file_path.open(encoding="utf-8") as file:
            data = json.load(file)

        if data.get("resourceType") == "Bundle":
            bundles.append(data)

    return bundles


def get_resource_types(bundle):
    return {
        entry.get("resource", {}).get("resourceType")
        for entry in bundle.get("entry", [])
    }


def test_fhir_bundle_generated():
    bundles = load_fhir_bundles()

    assert bundles, "No FHIR Bundles were generated"


def test_bundle_contains_patient():
    bundles = load_fhir_bundles()

    assert bundles, "No FHIR Bundles were generated"

    assert any(
        "Patient" in get_resource_types(bundle)
        for bundle in bundles
    ), "No generated FHIR Bundle contains a Patient resource"


def test_bundle_contains_encounter():
    bundles = load_fhir_bundles()

    assert bundles, "No FHIR Bundles were generated"

    assert any(
        "Encounter" in get_resource_types(bundle)
        for bundle in bundles
    ), "No generated FHIR Bundle contains an Encounter resource"