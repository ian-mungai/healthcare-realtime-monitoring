from lineage.openlineage.glue_lineage import NAMESPACE, PROCESSED_DATASET, RAW_DATASET, S3_LINEAGE_EVENT_PATH


def test_lineage_namespace() -> None:
    assert NAMESPACE == "healthcare-realtime-monitoring"


def test_raw_dataset() -> None:
    assert RAW_DATASET.namespace == "s3://<project-data-bucket>"
    assert RAW_DATASET.name == "raw/fhir_observations"


def test_processed_dataset() -> None:
    assert PROCESSED_DATASET.namespace == "aws-glue"
    assert PROCESSED_DATASET.name == "healthcare_realtime.processed_fhir_observations"


def test_s3_lineage_event_path() -> None:
    assert S3_LINEAGE_EVENT_PATH == "s3://<project-data-bucket>/lineage/openlineage/glue/event"
