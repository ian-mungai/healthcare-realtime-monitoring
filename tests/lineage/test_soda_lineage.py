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


def test_soda_lineage_namespace() -> None:
    assert NAMESPACE == "example-project"


def test_soda_input_datasets() -> None:
    assert STAGING_DATASET.name == "example_dbt.example_staging"
    assert DIM_PATIENT_DATASET.name == "example_dbt.example_dim_patient"
    assert DIM_OBSERVATION_TYPE_DATASET.name == "example_dbt.example_dim_observation_type"
    assert DIM_ENCOUNTER_DATASET.name == "example_dbt.example_dim_encounter"
    assert DIM_DATE_DATASET.name == "example_dbt.example_dim_date"
    assert DIM_PROVIDER_DATASET.name == "example_dbt.example_dim_provider"
    assert FACT_OBSERVATIONS_DATASET.name == "example_dbt.example_fact_observations"
    assert ENCOUNTER_FEATURES_DATASET.name == "example_dbt.example_encounter_features"
    assert ML_TRAINING_DATASET.name == "example_dbt.example_ml_training"


def test_soda_has_no_output_dataset_contract() -> None:
    event = build_soda_lineage_event(RunState.START, str(uuid4()))
    assert event.outputs == []


def test_soda_lineage_s3_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://example-data-bucket/lineage/openlineage/soda/event"
