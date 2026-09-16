from datetime import UTC, datetime
from uuid import uuid4

from openlineage.client.event_v2 import InputDataset, Job, Run, RunEvent, RunState

from lineage.openlineage.client import build_local_openlineage_client, emit_runtime_lineage_event
from lineage.openlineage.config import lineage_event_path, project_namespace, qualified_dataset

NAMESPACE = project_namespace()
PRODUCER = "https://github.com/OpenLineage/OpenLineage"
S3_LINEAGE_EVENT_PATH = lineage_event_path("soda")

STAGING_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_STAGING_TABLE"))
DIM_PATIENT_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_DIM_PATIENT_TABLE"))
DIM_OBSERVATION_TYPE_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_DIM_OBSERVATION_TYPE_TABLE"))
DIM_ENCOUNTER_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_DIM_ENCOUNTER_TABLE"))
DIM_DATE_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_DIM_DATE_TABLE"))
DIM_PROVIDER_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_DIM_PROVIDER_TABLE"))
FACT_OBSERVATIONS_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_FACT_OBSERVATIONS_TABLE"))
ENCOUNTER_FEATURES_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_ENCOUNTER_FEATURES_TABLE"))
ML_TRAINING_DATASET = InputDataset(namespace="aws-glue", name=qualified_dataset("ATHENA_DBT_DATABASE", "DBT_ML_TRAINING_TABLE"))


def build_soda_lineage_event(run_state: RunState, lineage_run_id: str) -> RunEvent:
    return RunEvent(
        eventType=run_state,
        eventTime=datetime.now(UTC).isoformat(),
        run=Run(runId=lineage_run_id),
        job=Job(namespace=NAMESPACE, name="soda_athena_contract_validation"),
        producer=PRODUCER,
        inputs=[
            STAGING_DATASET,
            DIM_PATIENT_DATASET,
            DIM_OBSERVATION_TYPE_DATASET,
            DIM_ENCOUNTER_DATASET,
            DIM_DATE_DATASET,
            DIM_PROVIDER_DATASET,
            FACT_OBSERVATIONS_DATASET,
            ENCOUNTER_FEATURES_DATASET,
            ML_TRAINING_DATASET,
        ],
        outputs=[],
    )


def emit_local_soda_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    build_local_openlineage_client("soda").emit(build_soda_lineage_event(run_state, lineage_run_id))
    return lineage_run_id


def emit_s3_soda_lineage(run_state: RunState, lineage_run_id: str | None = None) -> str:
    lineage_run_id = lineage_run_id or str(uuid4())
    emit_runtime_lineage_event(lineage_event_path("soda"), lambda: build_soda_lineage_event(run_state, lineage_run_id), "soda", run_state.value)
    return lineage_run_id
