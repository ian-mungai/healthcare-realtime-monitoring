import hashlib

SIMULATOR_IDENTIFIER_SYSTEM = "https://example.org/fhir/identifier/vitals-simulator"


def get_observation_code(observation: dict) -> str:
    coding = observation.get("code", {}).get("coding", [])

    if not coding:
        raise ValueError("Observation does not contain a code")

    code = coding[0].get("code")

    if not code:
        raise ValueError("Observation coding does not contain a code")

    return code


def get_patient_id(observation: dict) -> str:
    reference = observation.get("subject", {}).get("reference", "")

    if not reference.startswith("Patient/"):
        raise ValueError("Observation subject must reference a Patient")

    patient_id = reference.removeprefix("Patient/")

    if not patient_id:
        raise ValueError("Observation patient ID is required")

    return patient_id


def build_observation_identifier(patient_id: str, source_record_id: str, offset_seconds: int, observation_code: str) -> str:
    raw_identifier = f"{patient_id}:{source_record_id}:{offset_seconds}:{observation_code}"

    return hashlib.sha256(raw_identifier.encode("utf-8")).hexdigest()


def add_observation_identifier(observation: dict, source_record_id: str, offset_seconds: int) -> dict:
    patient_id = get_patient_id(observation)
    observation_code = get_observation_code(observation)

    identifier_value = build_observation_identifier(
        patient_id=patient_id, source_record_id=source_record_id, offset_seconds=offset_seconds, observation_code=observation_code
    )

    observation["identifier"] = [{"system": SIMULATOR_IDENTIFIER_SYSTEM, "value": identifier_value}]

    return observation
