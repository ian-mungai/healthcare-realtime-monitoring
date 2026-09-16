from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client.event_v2 import InputDataset, Job, OutputDataset, Run, RunEvent, RunState

from lineage.openlineage.client import build_local_openlineage_client, emit_runtime_lineage_event
from lineage.openlineage.config import data_bucket_name, lineage_event_path, project_namespace, qualified_dataset, required_env

PRODUCER = "https://github.com/OpenLineage/OpenLineage"


def build_glue_lineage_event(run_state: RunState, lineage_run_id: str) -> RunEvent:
    return RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=project_namespace(), name=required_env("GLUE_JOB_NAME")),
        producer=PRODUCER,
        inputs=[InputDataset(namespace=f"s3://{data_bucket_name()}", name="raw/fhir_observations")],
        outputs=[OutputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_SOURCE_DATABASE", "ATHENA_PROCESSED_TABLE"))],
    )


def emit_local_glue_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_local_openlineage_client("glue").emit(build_glue_lineage_event(run_state, lineage_run_id))
    return lineage_run_id


def emit_s3_glue_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    emit_runtime_lineage_event(lineage_event_path("glue"), lambda: build_glue_lineage_event(run_state, lineage_run_id), "glue", run_state.value)
    return lineage_run_id
