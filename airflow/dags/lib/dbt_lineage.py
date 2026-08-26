from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client import OpenLineageClient
from openlineage.client.event_v2 import Dataset, Job, Run, RunEvent, RunState
from openlineage.client.transport.file import FileConfig, FileTransport

NAMESPACE = "healthcare-realtime-monitoring"
PRODUCER = "https://github.com/OpenLineage/OpenLineage"
S3_LINEAGE_EVENT_PATH = "s3://imungai-healthcare-realtime/lineage/openlineage/dbt/event"

PROCESSED_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime.processed_fhir_observations")
STAGING_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.stg_fhir_observations")
DIM_PATIENT_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.dim_patient")
DIM_OBSERVATION_TYPE_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.dim_observation_type")
FACT_OBSERVATIONS_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.fact_observations")


def build_openlineage_client() -> OpenLineageClient:
    transport = FileTransport(FileConfig(log_file_path=S3_LINEAGE_EVENT_PATH, append=False))
    return OpenLineageClient(transport=transport)


def emit_dbt_lineage_event(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())

    event = RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=NAMESPACE, name="dbt_athena_build"),
        producer=PRODUCER,
        inputs=[PROCESSED_DATASET],
        outputs=[STAGING_DATASET, DIM_PATIENT_DATASET, DIM_OBSERVATION_TYPE_DATASET, FACT_OBSERVATIONS_DATASET],
    )

    build_openlineage_client().emit(event)

    return lineage_run_id
