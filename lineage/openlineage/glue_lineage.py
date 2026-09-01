from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client.event_v2 import Dataset, Job, Run, RunEvent, RunState

from lineage.openlineage.client import build_local_openlineage_client, build_s3_openlineage_client

NAMESPACE = "healthcare-realtime-monitoring"
PRODUCER = "https://github.com/OpenLineage/OpenLineage"
S3_LINEAGE_EVENT_PATH = "s3://imungai-healthcare-realtime/lineage/openlineage/glue/event"

RAW_DATASET = Dataset(namespace="s3://imungai-healthcare-realtime", name="raw/fhir_observations")
PROCESSED_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime.processed_fhir_observations")


def build_glue_lineage_event(run_state: RunState, lineage_run_id: str) -> RunEvent:
    return RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=NAMESPACE, name="healthcare_realtime_raw_to_processed"),
        producer=PRODUCER,
        inputs=[RAW_DATASET],
        outputs=[PROCESSED_DATASET],
    )


def emit_local_glue_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_local_openlineage_client("glue").emit(build_glue_lineage_event(run_state, lineage_run_id))
    return lineage_run_id


def emit_s3_glue_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_s3_openlineage_client(S3_LINEAGE_EVENT_PATH).emit(build_glue_lineage_event(run_state, lineage_run_id))
    return lineage_run_id
