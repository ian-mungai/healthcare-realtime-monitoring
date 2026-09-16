from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client.event_v2 import InputDataset, Job, OutputDataset, Run, RunEvent, RunState

from lineage.openlineage.client import build_local_openlineage_client, emit_runtime_lineage_event
from lineage.openlineage.config import lineage_event_path, project_namespace, qualified_dataset

PRODUCER = "https://github.com/OpenLineage/OpenLineage"


def build_athena_lineage_event(run_state: RunState, lineage_run_id: str) -> RunEvent:
    processed_dataset = InputDataset(
        namespace="aws-glue", name=qualified_dataset("ATHENA_SOURCE_DATABASE", "ATHENA_PROCESSED_TABLE")
    )
    return RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=project_namespace(), name="validate_processed_fhir_observations"),
        producer=PRODUCER,
        inputs=[processed_dataset],
        outputs=[OutputDataset(namespace="athena", name=f"{processed_dataset.name}_quality")],
    )


def emit_local_athena_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_local_openlineage_client("athena").emit(build_athena_lineage_event(run_state, lineage_run_id))
    return lineage_run_id


def emit_s3_athena_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    emit_runtime_lineage_event(lineage_event_path("athena"), lambda: build_athena_lineage_event(run_state, lineage_run_id), "athena", run_state.value)
    return lineage_run_id
