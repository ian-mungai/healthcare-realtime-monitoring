from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client.event_v2 import Dataset, Job, Run, RunEvent, RunState

from lineage.openlineage.client import build_local_openlineage_client, build_s3_openlineage_client
from lineage.openlineage.config import lineage_event_path

NAMESPACE = "healthcare-realtime-monitoring"
PRODUCER = "https://github.com/OpenLineage/OpenLineage"
S3_LINEAGE_EVENT_PATH = "s3://<project-data-bucket>/lineage/openlineage/dbt/event"

PROCESSED_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime.processed_fhir_observations")
STAGING_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.stg_fhir_observations")
DIM_PATIENT_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.dim_patient")
DIM_OBSERVATION_TYPE_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.dim_observation_type")
FACT_OBSERVATIONS_DATASET = Dataset(namespace="aws-glue", name="healthcare_realtime_dbt.fact_observations")


def build_dbt_lineage_event(run_state: RunState, lineage_run_id: str) -> RunEvent:
    return RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=NAMESPACE, name="dbt_athena_build"),
        producer=PRODUCER,
        inputs=[PROCESSED_DATASET],
        outputs=[STAGING_DATASET, DIM_PATIENT_DATASET, DIM_OBSERVATION_TYPE_DATASET, FACT_OBSERVATIONS_DATASET],
    )


def emit_local_dbt_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_local_openlineage_client("dbt").emit(build_dbt_lineage_event(run_state, lineage_run_id))
    return lineage_run_id


def emit_s3_dbt_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_s3_openlineage_client(lineage_event_path("dbt")).emit(build_dbt_lineage_event(run_state, lineage_run_id))
    return lineage_run_id
