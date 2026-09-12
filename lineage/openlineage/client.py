from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from openlineage.client import OpenLineageClient
from openlineage.client.serde import Serde
from openlineage.client.transport import Transport
from openlineage.client.transport.file import FileConfig, FileTransport
from openlineage.client.transport.http import HttpConfig, HttpTransport
from requests import PreparedRequest, Session
from requests.auth import AuthBase

LOCAL_LINEAGE_DIRECTORY = Path("lineage/events")


class AwsSigV4RequestsAuth(AuthBase):
    def __init__(self, region: str) -> None:
        self.region = region
        self.session = boto3.Session()

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        credentials = self.session.get_credentials()
        if credentials is None:
            raise RuntimeError("AWS credentials are required for the managed OpenLineage collector")

        aws_request = AWSRequest(method=request.method, url=request.url, data=request.body, headers=dict(request.headers))
        SigV4Auth(credentials.get_frozen_credentials(), "execute-api", self.region).add_auth(aws_request)
        request.headers.update(dict(aws_request.headers.items()))
        return request


def build_sigv4_session(region: str) -> Session:
    session = Session()
    session.auth = AwsSigV4RequestsAuth(region)
    return session


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


def emit_runtime_lineage_event(event_path: str, event_factory: Callable[[], Any], component: str, run_state: str) -> bool:
    try:
        build_runtime_openlineage_client(event_path).emit(event_factory())
    except Exception as error:
        print(f"OpenLineage {component} {run_state} emission failed: {type(error).__name__}: {error}")
        return False
    return True


def build_runtime_openlineage_client(event_path: str) -> OpenLineageClient:
    collector_url = os.getenv("OPENLINEAGE_URL", "").strip()
    if not collector_url:
        print("OpenLineage transport selected: S3")
        return build_s3_openlineage_client(event_path)

    parsed = urlparse(collector_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OPENLINEAGE_URL must be an absolute HTTP or HTTPS URL")

    endpoint = os.getenv("OPENLINEAGE_ENDPOINT", "api/v1/lineage").strip("/")
    if not endpoint:
        raise ValueError("OPENLINEAGE_ENDPOINT must not be empty")

    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        print("OpenLineage transport selected: local HTTP without authentication")
        session = None
    else:
        region = os.getenv("OPENLINEAGE_AWS_REGION", "").strip() or os.getenv("AWS_REGION", "").strip() or os.getenv("AWS_DEFAULT_REGION", "").strip()
        if not region:
            raise ValueError("OPENLINEAGE_AWS_REGION or AWS_REGION is required to sign requests to a remote OpenLineage collector")
        print(f"OpenLineage transport selected: SigV4 HTTP in {region}")
        session = build_sigv4_session(region)

    collector_base_url = f"{collector_url.rstrip('/')}/"
    return OpenLineageClient(transport=HttpTransport(HttpConfig(url=collector_base_url, endpoint=endpoint, session=session)))
