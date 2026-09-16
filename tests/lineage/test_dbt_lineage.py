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


def test_dbt_lineage_namespace() -> None:
    assert NAMESPACE == "example-project"


def test_dbt_input_dataset() -> None:
    assert PROCESSED_DATASET.namespace == "aws-glue"
    assert PROCESSED_DATASET.name == "example_source.example_processed_observations"


def test_dbt_output_datasets() -> None:
    assert STAGING_DATASET.name == "example_dbt.example_staging"
    assert DIM_PATIENT_DATASET.name == "example_dbt.example_dim_patient"
    assert DIM_OBSERVATION_TYPE_DATASET.name == "example_dbt.example_dim_observation_type"
    assert DIM_ENCOUNTER_DATASET.name == "example_dbt.example_dim_encounter"
    assert DIM_DATE_DATASET.name == "example_dbt.example_dim_date"
    assert DIM_PROVIDER_DATASET.name == "example_dbt.example_dim_provider"
    assert FACT_OBSERVATIONS_DATASET.name == "example_dbt.example_fact_observations"
    assert ENCOUNTER_FEATURES_DATASET.name == "example_dbt.example_encounter_features"
    assert ML_TRAINING_DATASET.name == "example_dbt.example_ml_training"


def test_dbt_lineage_s3_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://example-data-bucket/lineage/openlineage/dbt/event"
