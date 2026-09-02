from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import boto3
from openlineage.client import OpenLineageClient
from openlineage.client.serde import Serde
from openlineage.client.transport import Transport
from openlineage.client.transport.file import FileConfig, FileTransport

LOCAL_LINEAGE_DIRECTORY = Path("lineage/events")


class S3Transport(Transport):
    def __init__(self, event_path: str) -> None:
        parsed = urlparse(event_path)

        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError(f"Invalid S3 lineage event path: {event_path}")

        self.bucket = parsed.netloc
        self.key_prefix = parsed.path.lstrip("/")
        self.s3_client = boto3.client("s3")

    def emit(self, event) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S.%f")
        key = f"{self.key_prefix}-{timestamp}.json"
        body = json.dumps(Serde.to_dict(event), separators=(",", ":")).encode("utf-8")

        self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")


def build_local_openlineage_client(event_name: str) -> OpenLineageClient:
    LOCAL_LINEAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    transport = FileTransport(FileConfig(log_file_path=str(LOCAL_LINEAGE_DIRECTORY / f"{event_name}.jsonl"), append=False))
    return OpenLineageClient(transport=transport)


def build_s3_openlineage_client(event_path: str) -> OpenLineageClient:
    return OpenLineageClient(transport=S3Transport(event_path))
