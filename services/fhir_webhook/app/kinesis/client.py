import json
import os
from dataclasses import asdict, dataclass

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from services.fhir_webhook.app.models import FHIRWebhookEvent
from services.fhir_webhook.app.vitals import transform_fhir_vitals


@dataclass(frozen=True)
class KinesisPublishResult:
    shard_id: str
    sequence_number: str
    partition_key: str

    def to_dict(self) -> dict:
        return asdict(self)


class KinesisPublisherError(RuntimeError):
    pass


class KinesisPublisher:
    def __init__(self, stream_name: str | None = None, region_name: str | None = None):
        self.stream_name = stream_name or os.getenv("KINESIS_STREAM_NAME")
        self.region_name = region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")

        if not self.stream_name:
            raise RuntimeError("KINESIS_STREAM_NAME is not configured")

        if not self.region_name:
            raise RuntimeError("AWS_REGION is not configured")

        self.client = boto3.client("kinesis", region_name=self.region_name)

    def publish(self, event: FHIRWebhookEvent) -> KinesisPublishResult:
        payload = transform_fhir_vitals(event)
        partition_key = payload["patient_id"]
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        try:
            response = self.client.put_record(StreamName=self.stream_name, Data=data, PartitionKey=partition_key)
        except (BotoCoreError, ClientError) as error:
            raise KinesisPublisherError(f"Failed to publish event to Kinesis: {error}") from error

        return KinesisPublishResult(shard_id=response["ShardId"], sequence_number=response["SequenceNumber"], partition_key=partition_key)
