"""Rendering the Grafana dashboards from one source for each warehouse: the local Postgres and Athena on AWS.

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

Added with the Athena target (written before its code):

7. The Athena rendering keeps the Postgres query fields, so the Athena plugin finds no SQL or reads the format as text:
   Athena targets carry rawSQL, the plugin's numeric format and its default connection.
8. The AWS database and table names are typed into the renderer and drift from the deployment: they come from
   config/deployment.defaults.json, which the deployment config is rendered from.
9. The quarantine table's receive time is a string on AWS but a timestamp locally, so $__timeFilter compares a string
   with a timestamp on Athena: each target names its own receive-time expression.
10. A source uses a format the target does not map: stop and name it.
11. dbt names a model's table on AWS from the deployment config (an env_var alias), so the dashboard queries a table
    that does not exist when the configured name differs: the AWS rendering maps every aliased model a dashboard reads
    to its configured name.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.grafana import render_dashboards as render
from testkit import expect

ROOT = Path(__file__).resolve().parents[2]


def source(sql: str, uid: str = "test-dashboard") -> dict:
    return {"uid": uid, "title": "Test", "panels": [{"id": 1, "type": "table", "title": "Rows", "targets": [{"refId": "A", "format": "table", "sql": sql}]}]}


def test_a_surviving_placeholder_stops_rendering() -> None:
    with pytest.raises(render.RenderError, match="@@UNKNOWN@@"):
        render.render(source("select 1 from @@UNKNOWN@@.table_name"), render.target("local"))


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
    rendered = {name: render.render(dashboard, render.target("local")) for name, dashboard in sources.items()}

    expect.equal([rendered[name]["uid"] for name in sources], [dashboard["uid"] for dashboard in sources.values()])
    expect.equal(len({dashboard["uid"] for dashboard in rendered.values()}), len(rendered))


def test_every_rendered_panel_has_a_query_and_a_data_source() -> None:
    target = render.target("local")
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

    render.write(render.target("local"), first)
    render.write(render.target("local"), second)

    expect.equal(sorted(path.name for path in first.iterdir()), sorted(path.name for path in second.iterdir()))
    for path in first.iterdir():
        expect.equal(path.read_bytes(), (second / path.name).read_bytes())
        json.loads(path.read_text(encoding="utf-8"))


def test_athena_targets_use_the_athena_query_fields() -> None:
    target = render.target("aws")
    for dashboard in render.load_sources().values():
        for panel in render.render(dashboard, target)["panels"]:
            for query in panel["targets"]:
                expect.equal("rawSql" in query, False, panel["title"])
                expect.is_in(query["format"], (0, 1))
                expect.equal(query["connectionArgs"]["database"], "__default")
                expect.equal(query["datasource"], {"type": "grafana-athena-datasource", "uid": target.datasource_uid})


def test_aws_names_come_from_the_deployment_config() -> None:
    config = json.loads((ROOT / "config" / "deployment.defaults.json").read_text(encoding="utf-8"))["terraform"]
    rendered = render.render(source("select 1 from @@ANALYTICS@@.fact_observations union all select 1 from @@RAW@@.@@QUARANTINE@@"), render.target("aws"))

    sql = rendered["panels"][0]["targets"][0]["rawSQL"]

    expect.is_in(f"{config['dbt_database_name']}.fact_observations", sql)
    expect.is_in(f"{config['source_database_name']}.{config['quarantine_table_name']}", sql)


def test_the_quarantine_receive_time_is_parsed_on_athena_only() -> None:
    sql = "select 1 from @@RAW@@.@@QUARANTINE@@ where $__timeFilter(@@QUARANTINE_RECEIVED_AT@@)"
    local = render.render(source(sql), render.target("local"))["panels"][0]["targets"][0]["rawSql"]
    athena = render.render(source(sql), render.target("aws"))["panels"][0]["targets"][0]["rawSQL"]

    expect.is_in("$__timeFilter(received_at)", local)
    expect.is_in("from_iso8601_timestamp(received_at)", athena)


def test_an_unmapped_format_stops_rendering() -> None:
    dashboard = source("select 1")
    dashboard["panels"][0]["targets"][0]["format"] = "logs"
    with pytest.raises(render.RenderError, match="logs"):
        render.render(dashboard, render.target("aws"))


def aliased_models() -> set[str]:
    """Models whose table name dbt takes from an environment variable (dbt/dbt_project.yml)."""
    text = (ROOT / "dbt" / "dbt_project.yml").read_text(encoding="utf-8")
    return set(re.findall(r"^\s+([a-z0-9_]+):\n\s+\+alias: \"\{\{ env_var\(", text, re.MULTILINE))


def test_every_aliased_model_a_dashboard_reads_has_its_configured_aws_name() -> None:
    read = {table for dashboard in render.load_sources().values() for sql in render.queries(dashboard) for table in render.analytics_tables(sql)}
    target = render.target("aws")

    expect.equal(len(aliased_models()) >= 10, True, "the alias pattern no longer matches dbt_project.yml")
    expect.equal((read & aliased_models()) - set(target.tables), set())


def test_a_configured_table_name_replaces_the_model_name_on_aws(tmp_path: Path) -> None:
    defaults = json.loads((ROOT / "config" / "deployment.defaults.json").read_text(encoding="utf-8"))
    defaults["terraform"]["dbt_fact_observations_table_name"] = "observations_v2"
    path = tmp_path / "deployment.defaults.json"
    path.write_text(json.dumps(defaults), encoding="utf-8")

    rendered = render.render(source("select 1 from @@ANALYTICS@@.fact_observations"), render.aws_target(path))

    expect.is_in(f"{defaults['terraform']['dbt_database_name']}.observations_v2", rendered["panels"][0]["targets"][0]["rawSQL"])
