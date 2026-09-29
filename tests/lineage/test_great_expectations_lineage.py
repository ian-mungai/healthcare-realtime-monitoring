from lineage.openlineage.great_expectations_lineage import GX_VALIDATION_DATASET, NAMESPACE, PROCESSED_DATASET, S3_LINEAGE_EVENT_PATH
from testkit import expect


def test_great_expectations_lineage_namespace() -> None:
    expect.equal(NAMESPACE, "example-project")


def test_processed_dataset() -> None:
    expect.equal(PROCESSED_DATASET.namespace, "aws-glue")
    expect.equal(PROCESSED_DATASET.name, "example_source.example_processed_observations")


def test_great_expectations_validation_dataset() -> None:
    expect.equal(GX_VALIDATION_DATASET.namespace, "great-expectations")
    expect.equal(GX_VALIDATION_DATASET.name, "processed_fhir_observations_quality")


def test_great_expectations_lineage_s3_path() -> None:
    expect.equal(S3_LINEAGE_EVENT_PATH, "s3://example-data-bucket/lineage/openlineage/great_expectations/event")
