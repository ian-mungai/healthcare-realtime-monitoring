from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client.event_v2 import Dataset, Job, Run, RunEvent, RunState

from lineage.openlineage.client import build_local_openlineage_client, build_s3_openlineage_client
from lineage.openlineage.config import lineage_event_path

NAMESPACE = "healthcare-realtime-monitoring"
PRODUCER = "https://github.com/OpenLineage/OpenLineage"
S3_LINEAGE_EVENT_PATH = "s3://<project-data-bucket>/lineage/openlineage/athena/event"

PROCESSED_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime.processed_fhir_observations")
VALIDATION_DATASET = Dataset(namespace="athena", name="healthcare_realtime.processed_fhir_observations_quality")


def build_athena_lineage_event(run_state: RunState, lineage_run_id: str) -> RunEvent:
    return RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=NAMESPACE, name="validate_processed_fhir_observations"),
        producer=PRODUCER,
        inputs=[PROCESSED_DATASET],
        outputs=[VALIDATION_DATASET],
    )


def emit_local_athena_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_local_openlineage_client("athena").emit(build_athena_lineage_event(run_state, lineage_run_id))
    return lineage_run_id


def emit_s3_athena_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_s3_openlineage_client(lineage_event_path("athena")).emit(build_athena_lineage_event(run_state, lineage_run_id))
    return lineage_run_id
