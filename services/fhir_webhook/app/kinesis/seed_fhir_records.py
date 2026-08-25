from datetime import UTC, datetime, timedelta

from services.fhir_webhook.app.kinesis.client import KinesisPublisher
from services.fhir_webhook.app.models import FHIRWebhookEvent

PATIENT_ID = "step_11_patient_001"


def build_quantity_observation(observation_id: str, loinc_code: str, display: str, value: float, unit: str, ucum_code: str, effective_datetime: datetime) -> dict:
    return {
        "resourceType": "Observation",
        "id": observation_id,
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc_code, "display": display}], "text": display},
        "subject": {"reference": f"Patient/{PATIENT_ID}"},
        "effectiveDateTime": effective_datetime.isoformat(),
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": ucum_code},
    }


def build_blood_pressure_observation(observation_id: str, systolic: float, diastolic: float, effective_datetime: datetime) -> dict:
    return {
        "resourceType": "Observation",
        "id": observation_id,
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure systolic and diastolic"}], "text": "Blood pressure systolic and diastolic"},
        "subject": {"reference": f"Patient/{PATIENT_ID}"},
        "effectiveDateTime": effective_datetime.isoformat(),
        "component": [
            {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]}, "valueQuantity": {"value": systolic, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}},
            {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]}, "valueQuantity": {"value": diastolic, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}},
        ],
    }


def build_seed_observations() -> list[dict]:
    simulation_start = datetime.now(UTC)

    return [
        build_quantity_observation("step_11_hr_001", "8867-4", "Heart rate", 82.0, "beats/minute", "/min", simulation_start),
        build_quantity_observation("step_11_hr_002", "8867-4", "Heart rate", 84.0, "beats/minute", "/min", simulation_start + timedelta(seconds=1)),
        build_quantity_observation("step_11_hr_003", "8867-4", "Heart rate", 86.0, "beats/minute", "/min", simulation_start + timedelta(seconds=2)),
        build_quantity_observation("step_11_rr_001", "9279-1", "Respiratory rate", 18.0, "breaths/minute", "/min", simulation_start + timedelta(seconds=3)),
        build_quantity_observation("step_11_rr_002", "9279-1", "Respiratory rate", 19.0, "breaths/minute", "/min", simulation_start + timedelta(seconds=4)),
        build_quantity_observation("step_11_spo2_001", "2708-6", "Oxygen saturation in Arterial blood", 97.0, "%", "%", simulation_start + timedelta(seconds=5)),
        build_quantity_observation("step_11_spo2_002", "2708-6", "Oxygen saturation in Arterial blood", 98.0, "%", "%", simulation_start + timedelta(seconds=6)),
        build_quantity_observation("step_11_spo2_003", "2708-6", "Oxygen saturation in Arterial blood", 96.0, "%", "%", simulation_start + timedelta(seconds=7)),
        build_blood_pressure_observation("step_11_bp_001", 122.0, 78.0, simulation_start + timedelta(seconds=8)),
        build_blood_pressure_observation("step_11_bp_002", 125.0, 80.0, simulation_start + timedelta(seconds=9)),
    ]


def main():
    publisher = KinesisPublisher()
    observations = build_seed_observations()

    for index, observation in enumerate(observations, start=1):
        event = FHIRWebhookEvent(received_at=datetime.now(UTC), resource_type="Observation", resource_id=observation["id"], payload=observation)

        result = publisher.publish(event)

        print(f"{index}/10 id={observation['id']} shard={result.shard_id} partition={result.partition_key}")

    print()
    print(f"Published {len(observations)} clean FHIR Observation records.")


if __name__ == "__main__":
    main()
