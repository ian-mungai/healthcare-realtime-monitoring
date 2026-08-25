from pathlib import Path

from openlineage.client import OpenLineageClient
from openlineage.client.transport.file import FileConfig, FileTransport

LOCAL_LINEAGE_EVENT_PATH = Path("lineage/events/openlineage.jsonl")
S3_LINEAGE_EVENT_PATH = "s3://imungai-healthcare-realtime/lineage/openlineage/great_expectations/event"


def build_local_openlineage_client() -> OpenLineageClient:
    LOCAL_LINEAGE_EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)

    transport = FileTransport(FileConfig(log_file_path=str(LOCAL_LINEAGE_EVENT_PATH), append=False))

    return OpenLineageClient(transport=transport)


def build_s3_openlineage_client() -> OpenLineageClient:
    transport = FileTransport(FileConfig(log_file_path=S3_LINEAGE_EVENT_PATH, append=False))

    return OpenLineageClient(transport=transport)
