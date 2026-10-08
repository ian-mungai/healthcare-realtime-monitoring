"""Check the provisioned Grafana dashboards end to end on the local stack: every panel's query runs on the warehouse.

Usage: python -m e2e.local_grafana

Run it after the local stack is started and the study arm's warehouse is built. It reads the
Grafana admin password and port from deploy/local/.env. It checks that each dashboard rendered from
deploy/grafana/dashboards/ is provisioned under its uid, that every panel query runs through Grafana's query API on the
provisioned warehouse data source and returns rows (panels marked allowEmpty may return none), and that the Capacity
dashboard's census equals the warehouse's own count. Every run writes report.json and report.md under
artifacts/e2e/local_grafana/, passed, failed or blocked.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from e2e.local_stack import STACK_ENV_FILE, psql, setting
from e2e.report import ROOT, Blocked, Report
from scripts.grafana import render_dashboards as render
from scripts.infrastructure.render_project_config import load_environment_file

# The batch's encounters run from June 2026; the dashboards default to the last 180 days. The range is fixed once per
# run, so the census panel and the warehouse count cover the same hours: live admissions have synthetic discharge times
# in the future, which the panel's time filter leaves out (Oct 8 2026, AWS run).
RANGE_DAYS = 400
CENSUS_PANEL = "Census by unit"
CENSUS_TEMPLATE = "select sum(census) from {table} where hour_start between timestamp '{start}' and timestamp '{end}'"


@dataclass(frozen=True)
class QueryRange:
    start: datetime
    end: datetime

    @classmethod
    def ending_now(cls) -> QueryRange:
        end = datetime.now(UTC).replace(microsecond=0)
        return cls(start=end - timedelta(days=RANGE_DAYS), end=end)

    def grafana(self) -> dict[str, str]:
        return {"from": str(int(self.start.timestamp() * 1000)), "to": str(int(self.end.timestamp() * 1000))}

    def census_sql(self, table: str) -> str:
        """The warehouse's census over the same hours; both engines read a timestamp literal without a time zone as UTC."""
        return CENSUS_TEMPLATE.format(table=table, start=f"{self.start:%Y-%m-%d %H:%M:%S}", end=f"{self.end:%Y-%m-%d %H:%M:%S}")


PURPOSE = "The provisioned Grafana dashboards load under their uids and every panel query returns rows from the local warehouse."
LIMITS = (
    "Runs the panel queries through Grafana's query API, not a browser, so it does not check how panels draw. It covers "
    "the local Postgres warehouse only; the Athena rendering is checked on AWS by e2e.aws_grafana. Local results do "
    "not prove AWS behavior."
)
REPRODUCE = "Start the local stack, build the study warehouse, then run `.venv/bin/python -m e2e.local_grafana`."


def frame_rows(result: dict) -> int:
    """Rows in one query result: the length of the first field of each frame, summed."""
    return sum(len((frame.get("data", {}).get("values") or [[]])[0]) for frame in result.get("frames", []))


def frame_sum(result: dict) -> float:
    """The sum of every numeric value across a result's frames; long time series may come back one field per unit."""
    total = 0.0
    for frame in result.get("frames", []):
        fields = frame.get("schema", {}).get("fields", [])
        for field, values in zip(fields, frame.get("data", {}).get("values", []), strict=False):
            if field.get("type") == "number":
                total += sum(value or 0 for value in values)
    return total


def check_dashboards(report: Report, client: httpx.Client, query_range: QueryRange, warehouse_census: Callable[[QueryRange], float]) -> None:
    """Every dashboard is provisioned and every panel query runs through the data source the dashboard was rendered for;
    the census panel's total equals ``warehouse_census(query_range)``, the warehouse's own count over the same hours."""
    for name, source in render.load_sources().items():
        response = client.get(f"/api/dashboards/uid/{source['uid']}")
        report.check(f"{name}: provisioned", f"uid {source['uid']}", f"HTTP {response.status_code}", response.status_code == 200)
        if response.status_code != 200:
            continue
        dashboard = response.json()["dashboard"]
        for panel in dashboard.get("panels", []):
            if panel.get("type") == "row":
                continue
            for target in panel.get("targets", []):
                # The rendered target as the panel sends it; its query fields depend on the data source.
                query = {**query_range.grafana(), "queries": [target]}
                result = client.post("/api/ds/query", json=query)
                body = result.json().get("results", {}).get(target["refId"], {}) if result.status_code == 200 else {}
                rows = frame_rows(body)
                allow_empty = render.ALLOW_EMPTY in (panel.get("description") or "")
                report.check(
                    f"{name}: {panel['title']} ({target['refId']})",
                    "query runs" + ("" if allow_empty else " and returns rows"),
                    f"HTTP {result.status_code}, {rows} rows{', error ' + body['error'][:120] if body.get('error') else ''}",
                    result.status_code == 200 and not body.get("error") and (allow_empty or rows > 0),
                )
                if panel["title"] == CENSUS_PANEL:
                    shown = frame_sum(body)
                    direct = warehouse_census(query_range)
                    report.check("Census panel equals the warehouse", f"{direct:.0f} patient hours", f"{shown:.0f}", shown == direct and direct > 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=STACK_ENV_FILE, help="local stack settings written by local_stack.sh start")
    args = parser.parse_args(argv)
    report = Report(scenario="local_grafana", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        env = load_environment_file(args.env_file) if args.env_file.exists() else {}
        url = f"http://127.0.0.1:{setting(env, 'LOCAL_GRAFANA_PORT', '3000')}"
        query_range = QueryRange.ending_now()
        report.parameters = {"dashboards": sorted(render.load_sources()), "range": [query_range.start.isoformat(), query_range.end.isoformat()]}
        with httpx.Client(base_url=url, auth=("admin", setting(env, "LOCAL_GRAFANA_ADMIN_PASSWORD")), timeout=60) as client:
            try:
                client.get("/api/health")
            except httpx.TransportError:
                raise Blocked("Grafana is not reachable; start the stack with scripts/local/local_stack.sh start") from None
            check_dashboards(report, client, query_range, lambda window: float(psql("warehouse", window.census_sql("analytics.fact_unit_hourly_census")) or 0))
    except Exception as failure:
        error = failure
    report.finish(error)
    out = report.write()
    sys.stdout.write(f"local_grafana: {report.status} ({out.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
