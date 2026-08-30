from datetime import UTC, datetime

from services.fhir_webhook.app.kinesis.client import KinesisPublisher
from services.fhir_webhook.app.models import FHIRWebhookEvent


def main():
    event_time = datetime.now(UTC)

    observation = {
        "resourceType": "Observation",
        "id": "kinesis_smoke_test",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
        "subject": {"reference": "Patient/kinesis_test_patient"},
        "effectiveDateTime": event_time.isoformat(),
        "valueQuantity": {"value": 82.0, "unit": "beats/minute", "system": "http://unitsofmeasure.org", "code": "/min"},
    }

    event = FHIRWebhookEvent(received_at=event_time, resource_type="Observation", resource_id=observation["id"], payload=observation)

    publisher = KinesisPublisher()
    result = publisher.publish(event)

    print(f"Shard ID: {result.shard_id}")
    print(f"Sequence number: {result.sequence_number}")
    print(f"Partition key: {result.partition_key}")


if __name__ == "__main__":
    main()
