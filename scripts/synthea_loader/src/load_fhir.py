import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

FHIR_BASE_URL = "https://hapi.fhir.org/baseR4"

SYNTHEA_IDENTIFIER_SYSTEM = "https://github.com/synthetichealth/synthea"

FHIR_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "synthea" / "output" / "fhir"

STATE_DIR = Path(__file__).resolve().parents[1] / "state"

RESOURCE_MAP_FILE = STATE_DIR / "fhir_resource_map.json"


def load_bundle(file_path: Path) -> dict:
    """
    Load a FHIR JSON Bundle from disk.
    """
    with file_path.open(encoding="utf-8") as file:
        return json.load(file)


def contains_resource(bundle: dict, resource_type: str) -> bool:
    """
    Return True if a FHIR Bundle contains the requested
    resource type.
    """
    return any(entry.get("resource", {}).get("resourceType") == resource_type for entry in bundle.get("entry", []))


def find_patient_bundles() -> list[Path]:
    """
    Find Synthea FHIR Bundles containing Patient resources.

    This excludes hospitalInformation and
    practitionerInformation Bundles.
    """
    bundles = []

    for file_path in FHIR_OUTPUT_DIR.glob("*.json"):
        bundle = load_bundle(file_path)

        if bundle.get("resourceType") == "Bundle" and contains_resource(bundle, "Patient"):
            bundles.append(file_path)

    return bundles


def sanitize_patient(patient: dict) -> dict:
    """
    Remove optional external references from the Synthea
    Patient resource.

    Project 1 uses Synthea for patient identity/context.
    Provider information will later come from NPPES.
    """
    patient = json.loads(json.dumps(patient))

    patient.pop("managingOrganization", None)

    patient.pop("generalPractitioner", None)

    return patient


def sanitize_encounter(encounter: dict) -> dict:
    """
    Remove optional Synthea references that the public
    HAPI server rejects as inline match URLs.
    """
    encounter = json.loads(json.dumps(encounter))

    encounter.pop("participant", None)

    encounter.pop("serviceProvider", None)

    encounter.pop("location", None)

    return encounter


def select_seed_resources(bundle: dict) -> tuple[dict, dict]:
    """
    Select:

    - the Patient
    - the most recent Encounter

    from a complete Synthea patient Bundle.
    """
    patient = None
    encounters = []

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        resource_type = resource.get("resourceType")

        if resource_type == "Patient":
            patient = resource

        elif resource_type == "Encounter":
            encounters.append(resource)

    if patient is None:
        raise RuntimeError("No Patient resource found in Synthea bundle")

    if not encounters:
        raise RuntimeError("No Encounter resources found in Synthea bundle")

    most_recent_encounter = max(encounters, key=lambda encounter: encounter.get("period", {}).get("start", ""))

    return (sanitize_patient(patient), sanitize_encounter(most_recent_encounter))


def find_conditional_references(value) -> set[str]:
    """
    Recursively find references such as:

        Practitioner?identifier=...

    The public HAPI server currently rejects these inline
    match references.
    """
    references = set()

    if isinstance(value, dict):
        reference = value.get("reference")

        if isinstance(reference, str) and "?" in reference:
            references.add(reference)

        for child in value.values():
            references.update(find_conditional_references(child))

    elif isinstance(value, list):
        for child in value:
            references.update(find_conditional_references(child))

    return references


def get_synthea_identifier(resource: dict) -> tuple[str, str]:
    """
    Extract the Synthea identifier from a FHIR resource.

    Returns:

        (system, value)
    """
    identifiers = resource.get("identifier", [])

    for identifier in identifiers:
        system = identifier.get("system")

        value = identifier.get("value")

        if system == SYNTHEA_IDENTIFIER_SYSTEM and value:
            return system, value

    # Fallback to the first usable identifier.
    for identifier in identifiers:
        system = identifier.get("system")

        value = identifier.get("value")

        if system and value:
            return system, value

    raise RuntimeError(f"{resource.get('resourceType')} does not contain a usable identifier")


def search_resource_by_identifier(resource_type: str, system: str, value: str) -> dict | None:
    """
    Search HAPI for an existing resource using its
    FHIR identifier.

    Returns:
        resource dict if found
        None if not found
    """
    response = httpx.get(
        f"{FHIR_BASE_URL}/{resource_type}",
        params={"identifier": f"{system}|{value}", "_count": "10"},
        headers={"Accept": "application/fhir+json"},
        timeout=30.0,
    )

    response.raise_for_status()

    search_bundle = response.json()

    entries = search_bundle.get("entry", [])

    if not entries:
        return None

    if len(entries) > 1:
        print(f"WARNING: found {len(entries)} {resource_type} resources for identifier {system}|{value}.")

        print("Using the first matching resource.")

    return entries[0].get("resource")


def extract_id_from_location(location: str) -> str | None:
    """
    Extract a FHIR resource ID from a Location header.

    Supports values such as:

        Patient/123/_history/1

    and:

        https://hapi.fhir.org/baseR4/
        Patient/123/_history/1
    """
    parsed = urlparse(location)

    path = parsed.path if parsed.scheme else location

    parts = [part for part in path.split("/") if part]

    if "_history" in parts:
        history_index = parts.index("_history")

        if history_index >= 1:
            return parts[history_index - 1]

    if len(parts) >= 2:
        return parts[-1]

    return None


def create_resource(resource_type: str, resource: dict) -> dict:
    """
    Create one FHIR resource and return the server-side
    representation.

    Uses Prefer: return=representation so the response should
    contain the created resource.
    """
    response = httpx.post(
        f"{FHIR_BASE_URL}/{resource_type}",
        headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json", "Prefer": "return=representation"},
        json=resource,
        timeout=60.0,
    )

    print(f"Create {resource_type}: HTTP {response.status_code}")

    if response.is_error:
        print(f"\nFHIR {resource_type} creation failed:")

        try:
            print(json.dumps(response.json(), indent=2))

        except ValueError:
            print(response.text)

        raise RuntimeError(f"Failed to create {resource_type}: HTTP {response.status_code}")

    try:
        created = response.json()

    except ValueError:
        created = None

    if isinstance(created, dict) and created.get("id"):
        return created

    location = response.headers.get("location")

    if not location:
        raise RuntimeError(f"HAPI created {resource_type} but returned neither a resource body nor a Location header")

    resource_id = extract_id_from_location(location)

    if not resource_id:
        raise RuntimeError(f"Could not extract resource ID from Location: {location}")

    return get_resource(resource_type, resource_id)


def get_resource(resource_type: str, resource_id: str) -> dict:
    """
    Retrieve a FHIR resource by server-side ID.
    """
    response = httpx.get((f"{FHIR_BASE_URL}/{resource_type}/{resource_id}"), headers={"Accept": "application/fhir+json"}, timeout=30.0)

    response.raise_for_status()

    return response.json()


def load_resource_map() -> dict:
    """
    Load existing local Synthea -> HAPI mappings.
    """
    if not RESOURCE_MAP_FILE.exists():
        return {"patients": {}, "encounters": {}}

    with RESOURCE_MAP_FILE.open(encoding="utf-8") as file:
        return json.load(file)


def save_resource_map(resource_map: dict) -> None:
    """
    Save Synthea -> HAPI resource mappings.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with RESOURCE_MAP_FILE.open("w", encoding="utf-8") as file:
        json.dump(resource_map, file, indent=2, sort_keys=True)


def update_resource_map(synthea_patient_id: str, hapi_patient_id: str, synthea_encounter_id: str, hapi_encounter_id: str) -> dict:
    """
    Add or update Patient and Encounter mappings.
    """
    resource_map = load_resource_map()

    resource_map["patients"][synthea_patient_id] = hapi_patient_id

    resource_map["encounters"][synthea_encounter_id] = hapi_encounter_id

    save_resource_map(resource_map)

    return resource_map


def ensure_patient_exists(patient: dict) -> dict:
    """
    Return an existing HAPI Patient if the Synthea
    identifier already exists.

    Otherwise create the Patient.
    """
    system, value = get_synthea_identifier(patient)

    print("\nChecking Patient:")

    print(f"  identifier={system}|{value}")

    existing = search_resource_by_identifier("Patient", system, value)

    if existing is not None:
        print(f"  Existing Patient found: {existing.get('id')}")

        return existing

    print("  Patient not found.")

    print("  Creating Patient...")

    created = create_resource("Patient", patient)

    print(f"  Created Patient: {created.get('id')}")

    return created


def ensure_encounter_exists(encounter: dict, hapi_patient_id: str) -> dict:
    """
    Return an existing HAPI Encounter if its Synthea
    identifier already exists.

    Otherwise rewrite Encounter.subject to the actual HAPI
    Patient ID and create the Encounter.
    """
    system, value = get_synthea_identifier(encounter)

    print("\nChecking Encounter:")

    print(f"  identifier={system}|{value}")

    existing = search_resource_by_identifier("Encounter", system, value)

    if existing is not None:
        print(f"  Existing Encounter found: {existing.get('id')}")

        return existing

    print("  Encounter not found.")

    encounter = json.loads(json.dumps(encounter))

    encounter["subject"] = {"reference": f"Patient/{hapi_patient_id}"}

    conditional_references = find_conditional_references(encounter)

    if conditional_references:
        raise RuntimeError(f"Encounter still contains unsupported conditional references: {sorted(conditional_references)}")

    print("  Creating Encounter...")

    created = create_resource("Encounter", encounter)

    print(f"  Created Encounter: {created.get('id')}")

    return created


def main():
    """
    Idempotently seed Synthea Patient and Encounter
    resources into HAPI FHIR.

    Re-running this loader should reuse existing HAPI
    resources instead of creating duplicates.
    """
    bundles = find_patient_bundles()

    if not bundles:
        raise RuntimeError(f"No patient FHIR Bundles found in {FHIR_OUTPUT_DIR}")

    print(f"FHIR server: {FHIR_BASE_URL}")

    print(f"FHIR output directory: {FHIR_OUTPUT_DIR}")

    print(f"Found {len(bundles)} patient bundle(s)")

    for bundle_path in bundles:
        print("\n================================")

        print(f"Processing: {bundle_path.name}")

        print("================================")

        bundle = load_bundle(bundle_path)

        patient, encounter = select_seed_resources(bundle)

        synthea_patient_id = patient.get("id")

        synthea_encounter_id = encounter.get("id")

        if not synthea_patient_id:
            raise RuntimeError("Synthea Patient has no id")

        if not synthea_encounter_id:
            raise RuntimeError("Synthea Encounter has no id")

        print("\nSynthea resources:")

        print(f"  Patient: {synthea_patient_id}")

        print(f"  Encounter: {synthea_encounter_id}")

        patient_conditional_refs = find_conditional_references(patient)

        encounter_conditional_refs = find_conditional_references(encounter)

        if patient_conditional_refs:
            raise RuntimeError(f"Sanitized Patient still contains conditional references: {sorted(patient_conditional_refs)}")

        if encounter_conditional_refs:
            raise RuntimeError(f"Sanitized Encounter still contains conditional references: {sorted(encounter_conditional_refs)}")

        # -------------------------------------------------
        # Patient: find existing or create
        # -------------------------------------------------

        hapi_patient = ensure_patient_exists(patient)

        hapi_patient_id = hapi_patient.get("id")

        if not hapi_patient_id:
            raise RuntimeError("HAPI Patient has no id")

        # -------------------------------------------------
        # Encounter: find existing or create
        # -------------------------------------------------

        hapi_encounter = ensure_encounter_exists(encounter, hapi_patient_id)

        hapi_encounter_id = hapi_encounter.get("id")

        if not hapi_encounter_id:
            raise RuntimeError("HAPI Encounter has no id")

        # -------------------------------------------------
        # Verify resources by direct GET
        # -------------------------------------------------

        verified_patient = get_resource("Patient", hapi_patient_id)

        verified_encounter = get_resource("Encounter", hapi_encounter_id)

        if verified_patient.get("resourceType") != "Patient":
            raise RuntimeError("Retrieved resource is not a Patient")

        if verified_encounter.get("resourceType") != "Encounter":
            raise RuntimeError("Retrieved resource is not an Encounter")

        print("\nVerified HAPI resources:")

        print(f"  Patient/{hapi_patient_id}")

        print(f"  Encounter/{hapi_encounter_id}")

        # -------------------------------------------------
        # Save mapping
        # -------------------------------------------------

        resource_map = update_resource_map(synthea_patient_id, hapi_patient_id, synthea_encounter_id, hapi_encounter_id)

        print("\nFHIR resource mapping saved:")

        print(f"  {RESOURCE_MAP_FILE}")

        print("\nMapping counts:")

        print(f"  Patients: {len(resource_map['patients'])}")

        print(f"  Encounters: {len(resource_map['encounters'])}")

        print("\nFHIR seed verified successfully.")


if __name__ == "__main__":
    main()
