from typing import Any

from services.fhir_webhook.app.models import FHIRWebhookEvent

SCHEMA_VERSION = "1.0"

LOINC_VITAL_FIELDS = {"8867-4": "heart_rate", "9279-1": "respiratory_rate", "2708-6": "spo2"}

BLOOD_PRESSURE_CODE = "85354-9"
SYSTOLIC_CODE = "8480-6"
DIASTOLIC_CODE = "8462-4"


def get_loinc_code(code: dict[str, Any]) -> str | None:
    for coding in code.get("coding", []):
        if coding.get("system") == "http://loinc.org":
            return coding.get("code")

    return None


def get_patient_id(observation: dict[str, Any]) -> str:
    reference = observation.get("subject", {}).get("reference", "")

    if not reference.startswith("Patient/"):
        raise ValueError("FHIR Observation subject must reference a Patient")

    patient_id = reference.removeprefix("Patient/")

    if not patient_id:
        raise ValueError("FHIR Observation patient identifier is required")

    return patient_id


def get_event_timestamp(observation: dict[str, Any], event: FHIRWebhookEvent) -> str:
    return observation.get("effectiveDateTime") or event.received_at.isoformat()


def transform_fhir_vitals(event: FHIRWebhookEvent) -> dict[str, Any]:
    observation = event.payload
    loinc_code = get_loinc_code(observation.get("code", {}))

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "patient_id": get_patient_id(observation),
        "event_timestamp": get_event_timestamp(observation, event),
        "source": "fhir_webhook",
    }

    if loinc_code in LOINC_VITAL_FIELDS:
        value = observation.get("valueQuantity", {}).get("value")

        if value is None:
            raise ValueError(f"FHIR Observation {loinc_code} does not contain valueQuantity.value")

        payload[LOINC_VITAL_FIELDS[loinc_code]] = value

    elif loinc_code == BLOOD_PRESSURE_CODE:
        for component in observation.get("component", []):
            component_code = get_loinc_code(component.get("code", {}))
            value = component.get("valueQuantity", {}).get("value")

            if component_code == SYSTOLIC_CODE and value is not None:
                payload["systolic_bp"] = value

            elif component_code == DIASTOLIC_CODE and value is not None:
                payload["diastolic_bp"] = value

        if "systolic_bp" not in payload and "diastolic_bp" not in payload:
            raise ValueError("FHIR blood pressure Observation does not contain supported components")

    else:
        raise ValueError(f"Unsupported FHIR vital Observation LOINC code: {loinc_code}")

    return payload
