"""Rendering the Grafana dashboards from one source for each warehouse (the local Postgres now, Athena later).

Failure modes (written before the renderer):

1. A placeholder survives rendering, so a panel queries a table that does not exist: stop and name it.
2. A query uses Postgres-only syntax (a :: cast, FILTER (WHERE ...), INTERVAL 'n', ILIKE, NOW()), so the same dashboard
   would fail on Athena: the source check rejects it.
3. A dashboard's uid changes between renders or two dashboards share one, which breaks links: uids come from the
   source and are unique.
4. A panel renders without a query or a data source.
5. Two renders of the same source differ, which leaves the provisioned files changing for nothing: output is
   byte-identical.
6. A query names a warehouse table no dbt model builds (a typo): every analytics table is a dbt model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.grafana import render_dashboards as render
from testkit import expect

ROOT = Path(__file__).resolve().parents[2]


def source(sql: str, uid: str = "test-dashboard") -> dict:
    return {"uid": uid, "title": "Test", "panels": [{"id": 1, "type": "table", "title": "Rows", "targets": [{"refId": "A", "format": "table", "sql": sql}]}]}


def test_a_surviving_placeholder_stops_rendering() -> None:
    with pytest.raises(render.RenderError, match="@@UNKNOWN@@"):
        render.render(source("select 1 from @@UNKNOWN@@.table_name"), render.TARGETS["local"])


@pytest.mark.parametrize(
    "sql",
    [
        "select value::int from @@ANALYTICS@@.fact_observations",
        "select count(*) filter (where value > 1) from @@ANALYTICS@@.fact_observations",
        "select now() - interval '1 hour'",
        "select 1 from @@ANALYTICS@@.fact_observations where unit ilike 'x'",
    ],
)
def test_postgres_only_syntax_is_rejected(sql: str) -> None:
    expect.not_equal(render.portability_problems(sql), [])


def test_the_committed_dashboards_are_portable_and_name_real_models() -> None:
    sources = render.load_sources()
    models = {path.stem for path in (ROOT / "dbt" / "models").rglob("*.sql")}

    expect.equal(len(sources) >= 3, True)
    for name, dashboard in sources.items():
        for sql in render.queries(dashboard):
            expect.equal(render.portability_problems(sql), [], f"{name}: {sql[:60]}")
            expect.equal(set(render.analytics_tables(sql)) - models, set(), f"{name} names tables no dbt model builds")


def test_uids_are_stable_and_unique() -> None:
    sources = render.load_sources()
    rendered = {name: render.render(dashboard, render.TARGETS["local"]) for name, dashboard in sources.items()}

    expect.equal([rendered[name]["uid"] for name in sources], [dashboard["uid"] for dashboard in sources.values()])
    expect.equal(len({dashboard["uid"] for dashboard in rendered.values()}), len(rendered))


def test_every_rendered_panel_has_a_query_and_a_data_source() -> None:
    target = render.TARGETS["local"]
    for dashboard in render.load_sources().values():
        rendered = render.render(dashboard, target)
        for panel in rendered["panels"]:
            if panel["type"] == "row":
                continue
            expect.equal(panel["datasource"], {"type": target.datasource_type, "uid": target.datasource_uid})
            for query in panel["targets"]:
                expect.equal(bool(query.get("rawSql")), True, panel["title"])
                expect.equal(query["datasource"], panel["datasource"])


def test_rendering_twice_writes_identical_files(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"

    render.write(render.TARGETS["local"], first)
    render.write(render.TARGETS["local"], second)

    expect.equal(sorted(path.name for path in first.iterdir()), sorted(path.name for path in second.iterdir()))
    for path in first.iterdir():
        expect.equal(path.read_bytes(), (second / path.name).read_bytes())
        json.loads(path.read_text(encoding="utf-8"))
