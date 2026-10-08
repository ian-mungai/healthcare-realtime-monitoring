"""Render the Grafana dashboards in deploy/grafana/dashboards/ for one warehouse.

Usage: python -m scripts.grafana.render_dashboards --target local --output deploy/local/grafana/dashboards

Each source is a Grafana dashboard whose panel targets are written once, as {"refId", "format", "sql"}, with the
placeholders @@ANALYTICS@@ (the dbt schema or database), @@RAW@@ (the raw schema or Glue database) and @@QUARANTINE@@
(the quarantine table). Rendering sets each panel's data source, turns each target into the fields its data source
reads and fills the placeholders, so one source serves the local Postgres warehouse and, later, Athena. Queries keep to
SQL both engines run; portability_problems() names Postgres-only syntax. A panel whose description contains
ALLOW_EMPTY may return no rows. scripts/local/local_stack.sh renders the local target before it starts the stack.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "deploy" / "grafana" / "dashboards"
ALLOW_EMPTY = "May be empty."
PLACEHOLDER = re.compile(r"@@[A-Z_]+@@")
ANALYTICS_TABLE = re.compile(r"@@ANALYTICS@@\.([a-z0-9_]+)")
NON_PORTABLE = {
    ":: cast": re.compile(r"::"),
    "FILTER (WHERE ...)": re.compile(r"\bfilter\s*\(\s*where\b", re.IGNORECASE),
    "INTERVAL 'n'": re.compile(r"\binterval\s*'", re.IGNORECASE),
    "ILIKE": re.compile(r"\bilike\b", re.IGNORECASE),
    "NOW()": re.compile(r"\bnow\s*\(\s*\)", re.IGNORECASE),
}


class RenderError(ValueError):
    """A dashboard cannot be rendered for the target."""


@dataclass(frozen=True)
class Target:
    name: str
    datasource_type: str
    datasource_uid: str
    values: dict[str, str]


TARGETS = {
    "local": Target(
        name="local",
        datasource_type="grafana-postgresql-datasource",
        datasource_uid="warehouse",
        values={"ANALYTICS": "analytics", "RAW": "raw", "QUARANTINE": "processed_fhir_observations_quarantine"},
    )
}


def portability_problems(sql: str) -> list[str]:
    """The Postgres-only constructs in one query; Athena would reject each of them."""
    return [name for name, pattern in NON_PORTABLE.items() if pattern.search(sql)]


def analytics_tables(sql: str) -> list[str]:
    return ANALYTICS_TABLE.findall(sql)


def queries(dashboard: dict[str, Any]) -> list[str]:
    return [target["sql"] for panel in dashboard.get("panels", []) for target in panel.get("targets", [])]


def load_sources(directory: Path = SOURCE_DIR) -> dict[str, dict[str, Any]]:
    """Every dashboard source by file name, in name order."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))}


def _fill(text: str, target: Target) -> str:
    for name, value in target.values.items():
        text = text.replace(f"@@{name}@@", value)
    return text


def render(dashboard: dict[str, Any], target: Target) -> dict[str, Any]:
    """The dashboard with each panel's data source, targets and placeholders set for the target warehouse."""
    rendered = copy.deepcopy(dashboard)
    datasource = {"type": target.datasource_type, "uid": target.datasource_uid}
    for panel in rendered.get("panels", []):
        if panel.get("type") == "row":
            continue
        panel["datasource"] = datasource
        targets = []
        for query in panel.get("targets", []):
            problems = portability_problems(query["sql"])
            if problems:
                raise RenderError(f"{dashboard.get('uid')}: panel '{panel.get('title')}' uses {', '.join(problems)}")
            targets.append(
                {
                    "refId": query["refId"],
                    "datasource": datasource,
                    "editorMode": "code",
                    "format": query["format"],
                    "rawQuery": True,
                    "rawSql": _fill(query["sql"], target),
                }
            )
        panel["targets"] = targets
    text = _fill(json.dumps(rendered, sort_keys=True), target)
    left = sorted(set(PLACEHOLDER.findall(text)))
    if left:
        raise RenderError(f"{dashboard.get('uid')}: no {target.name} value for {', '.join(left)}")
    return json.loads(text)


def write(target: Target, output: Path, directory: Path = SOURCE_DIR) -> list[Path]:
    """Write every rendered dashboard to the output folder and remove files of dashboards that no longer exist."""
    output.mkdir(parents=True, exist_ok=True)
    rendered = {name: render(dashboard, target) for name, dashboard in load_sources(directory).items()}
    written = []
    for name, dashboard in rendered.items():
        path = output / f"{name}.json"
        path.write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    for stale in output.glob("*.json"):
        if stale.stem not in rendered:
            stale.unlink()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    written = write(TARGETS[args.target], args.output)
    sys.stdout.write(f"rendered {len(written)} dashboards for {args.target} into {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
