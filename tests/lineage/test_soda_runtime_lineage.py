from unittest.mock import Mock

from openlineage.client.event_v2 import RunState

from data_quality.soda import run_soda_with_lineage


def test_soda_runtime_emits_complete(monkeypatch) -> None:
    lineage_events = []

    monkeypatch.setattr(
        run_soda_with_lineage,
        "emit_s3_soda_lineage",
        lambda state, run_id=None: lineage_events.append((state, run_id)) or "00000000-0000-0000-0000-000000000001",
    )
    monkeypatch.setattr(run_soda_with_lineage.subprocess, "run", lambda *args, **kwargs: Mock(returncode=0))

    assert run_soda_with_lineage.main() == 0
    assert lineage_events == [(RunState.START, None), (RunState.COMPLETE, "00000000-0000-0000-0000-000000000001")]


def test_soda_runtime_emits_fail(monkeypatch) -> None:
    lineage_events = []

    monkeypatch.setattr(
        run_soda_with_lineage,
        "emit_s3_soda_lineage",
        lambda state, run_id=None: lineage_events.append((state, run_id)) or "00000000-0000-0000-0000-000000000001",
    )
    monkeypatch.setattr(run_soda_with_lineage.subprocess, "run", lambda *args, **kwargs: Mock(returncode=1))

    assert run_soda_with_lineage.main() == 1
    assert lineage_events == [(RunState.START, None), (RunState.FAIL, "00000000-0000-0000-0000-000000000001")]
