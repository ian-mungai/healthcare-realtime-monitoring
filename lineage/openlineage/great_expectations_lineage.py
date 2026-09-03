from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client.event_v2 import Dataset, Job, Run, RunEvent, RunState

from lineage.openlineage.client import build_s3_openlineage_client
from lineage.openlineage.config import lineage_event_path

NAMESPACE = "healthcare-realtime-monitoring"
PRODUCER = "https://github.com/OpenLineage/OpenLineage"
S3_LINEAGE_EVENT_PATH = "s3://<project-data-bucket>/lineage/openlineage/great_expectations/event"

PROCESSED_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime.processed_fhir_observations")
GX_VALIDATION_DATASET = Dataset(namespace="great-expectations", name="processed_fhir_observations_quality")


def emit_great_expectations_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())

    event = RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=NAMESPACE, name="great_expectations_processed_observations"),
        producer=PRODUCER,
        inputs=[PROCESSED_DATASET],
        outputs=[GX_VALIDATION_DATASET],
    )

    build_s3_openlineage_client(lineage_event_path("great_expectations")).emit(event)

    return lineage_run_id
