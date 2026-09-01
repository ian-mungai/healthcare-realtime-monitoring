from lineage.openlineage.great_expectations_lineage import GX_VALIDATION_DATASET, NAMESPACE, PROCESSED_DATASET, S3_LINEAGE_EVENT_PATH


def test_great_expectations_lineage_namespace() -> None:
    assert NAMESPACE == "healthcare-realtime-monitoring"


def test_processed_dataset() -> None:
    assert PROCESSED_DATASET.namespace == "aws-glue"
    assert PROCESSED_DATASET.name == "healthcare_realtime.processed_fhir_observations"


def test_great_expectations_validation_dataset() -> None:
    assert GX_VALIDATION_DATASET.namespace == "great-expectations"
    assert GX_VALIDATION_DATASET.name == "processed_fhir_observations_quality"


def test_great_expectations_lineage_s3_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://imungai-healthcare-realtime/lineage/openlineage/great_expectations/event"
