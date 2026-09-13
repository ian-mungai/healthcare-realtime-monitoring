from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.httpsession import URLLib3Session
from openlineage.client import OpenLineageClient
from openlineage.client.serde import Serde
from openlineage.client.transport import Transport
from openlineage.client.transport.file import FileConfig, FileTransport
from openlineage.client.transport.http import HttpConfig, HttpTransport
from requests import Response
from requests.exceptions import HTTPError

LOCAL_LINEAGE_DIRECTORY = Path("lineage/events")


class AwsSigV4HttpTransport(Transport):
    def __init__(self, url: str, endpoint: str, region: str) -> None:
        self.url = url
        self.endpoint = endpoint
        self.region = region
        self.session = URLLib3Session()

    def emit(self, event) -> Any:
        body = Serde.to_json(event).encode("utf-8")
        request = AWSRequest(method="POST", url=urljoin(self.url, self.endpoint), data=body, headers={"Content-Type": "application/json"})
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise RuntimeError("AWS credentials are required for the managed OpenLineage collector")

        SigV4Auth(credentials.get_frozen_credentials(), "execute-api", self.region).add_auth(request)
        response = self.session.send(request.prepare())
        if response.status_code >= 400:
            error_response = Response()
            error_response.status_code = response.status_code
            error_response._content = response.content
            error_response.url = request.url
            raise HTTPError(f"{response.status_code} response from OpenLineage collector", response=error_response)
        return response


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
    except HTTPError as error:
        response = error.response
        status = response.status_code if response is not None else "unknown"
        response_text = " ".join(response.text.split())[:1000] if response is not None else "unavailable"
        print(f"OpenLineage {component} {run_state} emission failed: HTTPError: status={status}; response={response_text or 'empty'}")
        return False
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
        transport: Transport = HttpTransport(HttpConfig(url=f"{collector_url.rstrip('/')}/", endpoint=endpoint, session=None))
    else:
        region = os.getenv("OPENLINEAGE_AWS_REGION", "").strip() or os.getenv("AWS_REGION", "").strip() or os.getenv("AWS_DEFAULT_REGION", "").strip()
        if not region:
            raise ValueError("OPENLINEAGE_AWS_REGION or AWS_REGION is required to sign requests to a remote OpenLineage collector")
        print(f"OpenLineage transport selected: SigV4 HTTP in {region}")
        transport = AwsSigV4HttpTransport(f"{collector_url.rstrip('/')}/", endpoint, region)

    return OpenLineageClient(transport=transport)
