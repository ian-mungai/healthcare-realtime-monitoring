from pathlib import Path

from openlineage.client import OpenLineageClient
from openlineage.client.transport.file import FileConfig, FileTransport

LOCAL_LINEAGE_DIRECTORY = Path("lineage/events")


def build_local_openlineage_client(event_name: str) -> OpenLineageClient:
    LOCAL_LINEAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    transport = FileTransport(FileConfig(log_file_path=str(LOCAL_LINEAGE_DIRECTORY / f"{event_name}.jsonl"), append=False))
    return OpenLineageClient(transport=transport)


def build_s3_openlineage_client(event_path: str) -> OpenLineageClient:
    transport = FileTransport(FileConfig(log_file_path=event_path, append=False))
    return OpenLineageClient(transport=transport)
