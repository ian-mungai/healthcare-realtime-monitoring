from uuid import uuid4

from openlineage.client.event_v2 import RunState

from lineage.openlineage.soda_lineage import (
    DIM_DATE_DATASET,
    DIM_ENCOUNTER_DATASET,
    DIM_OBSERVATION_TYPE_DATASET,
    DIM_PATIENT_DATASET,
    DIM_PROVIDER_DATASET,
    ENCOUNTER_FEATURES_DATASET,
    FACT_OBSERVATIONS_DATASET,
    ML_TRAINING_DATASET,
    NAMESPACE,
    S3_LINEAGE_EVENT_PATH,
    STAGING_DATASET,
    build_soda_lineage_event,
)
from testkit import expect


def test_soda_lineage_namespace() -> None:
    expect.equal(NAMESPACE, "example-project")


def test_soda_input_datasets() -> None:
    expect.equal(STAGING_DATASET.name, "example_dbt.example_staging")
    expect.equal(DIM_PATIENT_DATASET.name, "example_dbt.example_dim_patient")
    expect.equal(DIM_OBSERVATION_TYPE_DATASET.name, "example_dbt.example_dim_observation_type")
    expect.equal(DIM_ENCOUNTER_DATASET.name, "example_dbt.example_dim_encounter")
    expect.equal(DIM_DATE_DATASET.name, "example_dbt.example_dim_date")
    expect.equal(DIM_PROVIDER_DATASET.name, "example_dbt.example_dim_provider")
    expect.equal(FACT_OBSERVATIONS_DATASET.name, "example_dbt.example_fact_observations")
    expect.equal(ENCOUNTER_FEATURES_DATASET.name, "example_dbt.example_encounter_features")
    expect.equal(ML_TRAINING_DATASET.name, "example_dbt.example_ml_training")


def test_soda_has_no_output_dataset_contract() -> None:
    event = build_soda_lineage_event(RunState.START, str(uuid4()))
    expect.equal(event.outputs, [])


def test_soda_lineage_s3_path() -> None:
    expect.equal(S3_LINEAGE_EVENT_PATH, "s3://example-data-bucket/lineage/openlineage/soda/event")
