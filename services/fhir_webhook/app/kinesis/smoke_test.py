from datetime import UTC, datetime

from services.fhir_webhook.app.kinesis.client import KinesisPublisher
from services.fhir_webhook.app.models import FHIRWebhookEvent


def main():
    event = FHIRWebhookEvent(received_at=datetime.now(UTC), resource_type="Observation", resource_id="kinesis_smoke_test", payload={"resourceType": "Observation", "id": "kinesis_smoke_test", "status": "final", "subject": {"reference": "Patient/kinesis_test_patient"}})

    publisher = KinesisPublisher()
    result = publisher.publish(event)

    print(f"Shard ID: {result.shard_id}")
    print(f"Sequence number: {result.sequence_number}")
    print(f"Partition key: {result.partition_key}")


if __name__ == "__main__":
    main()
