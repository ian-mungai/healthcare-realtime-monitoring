from uuid import uuid4

from openlineage.client.event_v2 import RunState

from lineage.openlineage.soda_lineage import (
    DIM_OBSERVATION_TYPE_DATASET,
    DIM_PATIENT_DATASET,
    FACT_OBSERVATIONS_DATASET,
    NAMESPACE,
    S3_LINEAGE_EVENT_PATH,
    STAGING_DATASET,
    build_soda_lineage_event,
)


def test_soda_lineage_namespace() -> None:
    assert NAMESPACE == "healthcare-realtime-monitoring"


def test_soda_input_datasets() -> None:
    assert STAGING_DATASET.name == "healthcare_realtime_dbt.stg_fhir_observations"
    assert DIM_PATIENT_DATASET.name == "healthcare_realtime_dbt.dim_patient"
    assert DIM_OBSERVATION_TYPE_DATASET.name == "healthcare_realtime_dbt.dim_observation_type"
    assert FACT_OBSERVATIONS_DATASET.name == "healthcare_realtime_dbt.fact_observations"


def test_soda_has_no_output_dataset_contract() -> None:
    event = build_soda_lineage_event(RunState.START, str(uuid4()))
    assert event.outputs == []


def test_soda_lineage_s3_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://imungai-healthcare-realtime/lineage/openlineage/soda/event"
