"""Render the Grafana dashboards in deploy/grafana/dashboards/ for one warehouse.

Usage: python -m scripts.grafana.render_dashboards --target local|aws --output <FOLDER>

Each source is a Grafana dashboard whose panel targets are written once, as {"refId", "format", "sql"}, with the
placeholders @@ANALYTICS@@ (the dbt schema or database), @@RAW@@ (the raw schema or Glue database), @@QUARANTINE@@
(the quarantine table) and @@QUARANTINE_RECEIVED_AT@@ (its receive time as a timestamp: a timestamp column locally, an
ISO 8601 string on AWS). Rendering sets each panel's data source, turns each target into the fields its data source
reads and fills the placeholders, so one source serves the local Postgres warehouse and Athena. Queries keep to SQL both
engines run; portability_problems() names Postgres-only syntax. A panel whose description contains ALLOW_EMPTY may
return no rows. scripts/local/local_stack.sh renders the local target before it starts the stack; the Grafana image
(deploy/grafana/Dockerfile) is built with the aws target, whose names come from config/deployment.defaults.json.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "deploy" / "grafana" / "dashboards"
# The deployment names the Grafana image needs; scripts/infrastructure/render_project_config.py takes them from here too.
DEPLOYMENT_DEFAULTS = ROOT / "config" / "deployment.defaults.json"
# Models whose AWS table name dbt takes from the deployment config (an env_var alias in dbt/dbt_project.yml), by the
# config key that names them; the local runner uses the model names (jobs/local_warehouse/dbt.py).
AWS_TABLE_NAMES = {"fact_observations": "dbt_fact_observations_table_name", "ml_training_dataset": "dbt_ml_training_table_name"}
# The Athena plugin's own value for "the data source's region, catalog or database".
ATHENA_DEFAULT = "__default"
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
    """One warehouse: its data source, the query field holding the SQL, the format values it reads and the fields every
    query also carries."""

    name: str
    datasource_type: str
    datasource_uid: str
    values: dict[str, str]
    sql_field: str
    formats: dict[str, str | int]
    fields: dict[str, Any]
    # Models whose table has another name in this warehouse.
    tables: dict[str, str] = field(default_factory=dict)


LOCAL = Target(
    name="local",
    datasource_type="grafana-postgresql-datasource",
    datasource_uid="warehouse",
    values={"ANALYTICS": "analytics", "RAW": "raw", "QUARANTINE": "processed_fhir_observations_quarantine", "QUARANTINE_RECEIVED_AT": "received_at"},
    sql_field="rawSql",
    formats={"time_series": "time_series", "table": "table"},
    fields={"editorMode": "code", "rawQuery": True},
)
TARGET_NAMES = ("aws", "local")


def aws_target(defaults_path: Path = DEPLOYMENT_DEFAULTS) -> Target:
    """Athena through the grafana-athena-datasource plugin, with the Glue names the deployment configures."""
    config = json.loads(defaults_path.read_text(encoding="utf-8"))["terraform"]
    return Target(
        name="aws",
        datasource_type="grafana-athena-datasource",
        datasource_uid="athena",
        values={
            "ANALYTICS": config["dbt_database_name"],
            "RAW": config["source_database_name"],
            "QUARANTINE": config["quarantine_table_name"],
            # The same parse as the dbt macro parse_timestamp on Athena.
            "QUARANTINE_RECEIVED_AT": "cast(from_iso8601_timestamp(received_at) at time zone 'UTC' as timestamp)",
        },
        sql_field="rawSQL",
        # The plugin's FormatOptions: 0 is a time series, 1 a table.
        formats={"time_series": 0, "table": 1},
        fields={"connectionArgs": {"region": ATHENA_DEFAULT, "catalog": ATHENA_DEFAULT, "database": ATHENA_DEFAULT}},
        tables={model: config[key] for model, key in AWS_TABLE_NAMES.items()},
    )


def target(name: str) -> Target:
    if name == "local":
        return LOCAL
    if name == "aws":
        return aws_target()
    raise RenderError(f"no target {name!r}; choose one of {', '.join(TARGET_NAMES)}")


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
    text = ANALYTICS_TABLE.sub(lambda match: f"@@ANALYTICS@@.{target.tables.get(match.group(1), match.group(1))}", text)
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
            if query["format"] not in target.formats:
                raise RenderError(f"{dashboard.get('uid')}: panel '{panel.get('title')}' uses format {query['format']}, which {target.name} does not map")
            targets.append(
                {
                    **copy.deepcopy(target.fields),
                    "refId": query["refId"],
                    "datasource": datasource,
                    "format": target.formats[query["format"]],
                    target.sql_field: _fill(query["sql"], target),
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
    parser.add_argument("--target", choices=TARGET_NAMES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    written = write(target(args.target), args.output)
    sys.stdout.write(f"rendered {len(written)} dashboards for {args.target} into {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
