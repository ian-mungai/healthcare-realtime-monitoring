from lineage.openlineage.dbt_lineage import (
    DIM_DATE_DATASET,
    DIM_ENCOUNTER_DATASET,
    DIM_OBSERVATION_TYPE_DATASET,
    DIM_PATIENT_DATASET,
    DIM_PROVIDER_DATASET,
    ENCOUNTER_FEATURES_DATASET,
    FACT_OBSERVATIONS_DATASET,
    ML_TRAINING_DATASET,
    NAMESPACE,
    PROCESSED_DATASET,
    S3_LINEAGE_EVENT_PATH,
    STAGING_DATASET,
)
from testkit import expect


def test_dbt_lineage_namespace() -> None:
    expect.equal(NAMESPACE, "example-project")


def test_dbt_input_dataset() -> None:
    expect.equal(PROCESSED_DATASET.namespace, "aws-glue")
    expect.equal(PROCESSED_DATASET.name, "example_source.example_processed_observations")


def test_dbt_output_datasets() -> None:
    expect.equal(STAGING_DATASET.name, "example_dbt.example_staging")
    expect.equal(DIM_PATIENT_DATASET.name, "example_dbt.example_dim_patient")
    expect.equal(DIM_OBSERVATION_TYPE_DATASET.name, "example_dbt.example_dim_observation_type")
    expect.equal(DIM_ENCOUNTER_DATASET.name, "example_dbt.example_dim_encounter")
    expect.equal(DIM_DATE_DATASET.name, "example_dbt.example_dim_date")
    expect.equal(DIM_PROVIDER_DATASET.name, "example_dbt.example_dim_provider")
    expect.equal(FACT_OBSERVATIONS_DATASET.name, "example_dbt.example_fact_observations")
    expect.equal(ENCOUNTER_FEATURES_DATASET.name, "example_dbt.example_encounter_features")
    expect.equal(ML_TRAINING_DATASET.name, "example_dbt.example_ml_training")


def test_dbt_lineage_s3_path() -> None:
    expect.equal(S3_LINEAGE_EVENT_PATH, "s3://example-data-bucket/lineage/openlineage/dbt/event")
