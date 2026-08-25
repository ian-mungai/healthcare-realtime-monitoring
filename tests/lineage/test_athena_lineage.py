from airflow.dags.lib.athena_lineage import NAMESPACE, PROCESSED_DATASET, S3_LINEAGE_EVENT_PATH, VALIDATION_DATASET


def test_athena_lineage_namespace() -> None:
    assert NAMESPACE == "healthcare-realtime-monitoring"


def test_processed_dataset() -> None:
    assert PROCESSED_DATASET.namespace == "aws-glue"
    assert PROCESSED_DATASET.name == "healthcare_realtime.processed_fhir_observations"


def test_validation_dataset() -> None:
    assert VALIDATION_DATASET.namespace == "athena"
    assert VALIDATION_DATASET.name == "healthcare_realtime.processed_fhir_observations_quality"


def test_athena_lineage_s3_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://imungai-healthcare-realtime/lineage/openlineage/athena/event"
