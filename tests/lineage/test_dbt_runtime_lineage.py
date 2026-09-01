from unittest.mock import Mock

from openlineage.client.event_v2 import RunState

from jobs.dbt import run_dbt_with_lineage


def test_dbt_runtime_emits_complete(monkeypatch) -> None:
    lineage_events = []

    monkeypatch.setattr(
        run_dbt_with_lineage, "emit_s3_dbt_lineage", lambda state, run_id=None: lineage_events.append((state, run_id)) or "00000000-0000-0000-0000-000000000001"
    )
    monkeypatch.setattr(run_dbt_with_lineage.subprocess, "run", lambda *args, **kwargs: Mock(returncode=0))
    monkeypatch.setattr(run_dbt_with_lineage.sys, "argv", ["run_dbt_with_lineage.py", "build"])

    assert run_dbt_with_lineage.main() == 0
    assert lineage_events == [(RunState.START, None), (RunState.COMPLETE, "00000000-0000-0000-0000-000000000001")]


def test_dbt_runtime_emits_fail(monkeypatch) -> None:
    lineage_events = []

    monkeypatch.setattr(
        run_dbt_with_lineage, "emit_s3_dbt_lineage", lambda state, run_id=None: lineage_events.append((state, run_id)) or "00000000-0000-0000-0000-000000000001"
    )
    monkeypatch.setattr(run_dbt_with_lineage.subprocess, "run", lambda *args, **kwargs: Mock(returncode=1))
    monkeypatch.setattr(run_dbt_with_lineage.sys, "argv", ["run_dbt_with_lineage.py", "build"])

    assert run_dbt_with_lineage.main() == 1
    assert lineage_events == [(RunState.START, None), (RunState.FAIL, "00000000-0000-0000-0000-000000000001")]
