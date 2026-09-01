from uuid import uuid4

from openlineage.client.event_v2 import RunState

from lineage.openlineage.athena_lineage import build_athena_lineage_event
from lineage.openlineage.dbt_lineage import build_dbt_lineage_event
from lineage.openlineage.glue_lineage import build_glue_lineage_event
from lineage.openlineage.soda_lineage import build_soda_lineage_event


def test_glue_lineage_reuses_run_id() -> None:
    run_id = str(uuid4())
    start = build_glue_lineage_event(RunState.START, run_id)
    complete = build_glue_lineage_event(RunState.COMPLETE, run_id)
    assert start.run.runId == complete.run.runId == run_id


def test_athena_lineage_reuses_run_id() -> None:
    run_id = str(uuid4())
    start = build_athena_lineage_event(RunState.START, run_id)
    complete = build_athena_lineage_event(RunState.COMPLETE, run_id)
    assert start.run.runId == complete.run.runId == run_id


def test_dbt_lineage_reuses_run_id() -> None:
    run_id = str(uuid4())
    start = build_dbt_lineage_event(RunState.START, run_id)
    complete = build_dbt_lineage_event(RunState.COMPLETE, run_id)
    assert start.run.runId == complete.run.runId == run_id


def test_soda_lineage_reuses_run_id() -> None:
    run_id = str(uuid4())
    start = build_soda_lineage_event(RunState.START, run_id)
    fail = build_soda_lineage_event(RunState.FAIL, run_id)
    assert start.run.runId == fail.run.runId == run_id
