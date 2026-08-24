from datetime import UTC, datetime, timedelta

from services.fhir_webhook.app.kinesis.client import KinesisPublisher
from services.fhir_webhook.app.models import FHIRWebhookEvent

PATIENT_ID = "step_12_patient_001"


def build_observation(observation_id: str, loinc_code: str, display: str, value: float, unit: str, effective_datetime: datetime) -> dict:
    return {
        "resourceType": "Observation",
        "id": observation_id,
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": loinc_code,
                    "display": display,
                }
            ]
        },
        "subject": {
            "reference": f"Patient/{PATIENT_ID}",
        },
        "effectiveDateTime": effective_datetime.isoformat(),
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": "http://unitsofmeasure.org",
        },
    }


def build_incremental_observations() -> list[dict]:
    simulation_start = datetime.now(UTC)

    return [
        build_observation("step_12_hr_003", "8867-4", "Heart rate", 79.0, "beats/minute", simulation_start),
        build_observation("step_12_rr_003", "9279-1", "Respiratory rate", 17.0, "breaths/minute", simulation_start + timedelta(seconds=1)),
        build_observation("step_12_spo2_003", "2708-6", "Oxygen saturation", 98.0, "%", simulation_start + timedelta(seconds=2)),
        build_observation("step_12_hr_invalid_003", "8867-4", "Heart rate", 500.0, "beats/minute", simulation_start + timedelta(seconds=3)),
    ]


def main():
    publisher = KinesisPublisher()
    observations = build_incremental_observations()

    for index, observation in enumerate(observations, start=1):
        event = FHIRWebhookEvent(
            received_at=datetime.now(UTC),
            resource_type="Observation",
            resource_id=observation["id"],
            payload=observation,
        )

        result = publisher.publish(event)

        print(f"{index}/{len(observations)} id={observation['id']} shard={result.shard_id} partition={result.partition_key}")

    print()
    print(f"Published {len(observations)} incremental FHIR Observation records.")


if __name__ == "__main__":
    main()