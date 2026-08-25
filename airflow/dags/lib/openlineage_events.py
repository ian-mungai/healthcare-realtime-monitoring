from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client import OpenLineageClient
from openlineage.client.event_v2 import Dataset, Job, Run, RunEvent, RunState
from openlineage.client.transport.file import FileConfig, FileTransport

NAMESPACE = "healthcare-realtime-monitoring"
PRODUCER = "https://github.com/OpenLineage/OpenLineage"
S3_LINEAGE_EVENT_PATH = "s3://imungai-healthcare-realtime/lineage/openlineage/glue/event"

RAW_DATASET = Dataset(namespace="s3://imungai-healthcare-realtime", name="raw/fhir_observations")
PROCESSED_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime.processed_fhir_observations")


def build_openlineage_client() -> OpenLineageClient:
    transport = FileTransport(FileConfig(log_file_path=S3_LINEAGE_EVENT_PATH))
    return OpenLineageClient(transport=transport)


def emit_glue_lineage_event(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())

    event = RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=NAMESPACE, name="healthcare_realtime_raw_to_processed"),
        producer=PRODUCER,
        inputs=[RAW_DATASET],
        outputs=[PROCESSED_DATASET],
    )

    build_openlineage_client().emit(event)

    return lineage_run_id
