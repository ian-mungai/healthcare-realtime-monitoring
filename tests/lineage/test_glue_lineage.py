from openlineage.client.event_v2 import RunState

from lineage.openlineage.glue_lineage import build_glue_lineage_event
from testkit import expect


def event():
    return build_glue_lineage_event(RunState.START, "11111111-1111-4111-8111-111111111111")


def test_lineage_namespace() -> None:
    expect.equal(event().job.namespace, "example-project")


def test_raw_dataset() -> None:
    expect.equal(event().inputs[0].namespace, "s3://example-data-bucket")
    expect.equal(event().inputs[0].name, "raw/fhir_observations")


def test_processed_dataset() -> None:
    expect.equal(event().outputs[0].namespace, "aws-glue")
    expect.equal(event().outputs[0].name, "example_source.example_processed_observations")
