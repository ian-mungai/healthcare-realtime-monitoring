from lineage.openlineage.dbt_lineage import (
    DIM_OBSERVATION_TYPE_DATASET,
    DIM_PATIENT_DATASET,
    FACT_OBSERVATIONS_DATASET,
    NAMESPACE,
    PROCESSED_DATASET,
    S3_LINEAGE_EVENT_PATH,
    STAGING_DATASET,
)


def test_dbt_lineage_namespace() -> None:
    assert NAMESPACE == "healthcare-realtime-monitoring"


def test_dbt_input_dataset() -> None:
    assert PROCESSED_DATASET.namespace == "aws-glue"
    assert PROCESSED_DATASET.name == "healthcare_realtime.processed_fhir_observations"


def test_dbt_output_datasets() -> None:
    assert STAGING_DATASET.name == "healthcare_realtime_dbt.stg_fhir_observations"
    assert DIM_PATIENT_DATASET.name == "healthcare_realtime_dbt.dim_patient"
    assert DIM_OBSERVATION_TYPE_DATASET.name == "healthcare_realtime_dbt.dim_observation_type"
    assert FACT_OBSERVATIONS_DATASET.name == "healthcare_realtime_dbt.fact_observations"


def test_dbt_lineage_s3_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://<project-data-bucket>/lineage/openlineage/dbt/event"
