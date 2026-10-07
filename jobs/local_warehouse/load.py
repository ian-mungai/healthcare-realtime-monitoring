"""Load the batch vitals into the local warehouse in the same row format the AWS Glue job writes.

Usage: python -m jobs.local_warehouse.load [--batch DIRECTORY]

Each batch record becomes one processed row per measurement, with the Glue job's names, units, analytical ranges and
merge rule (jobs/glue/fhir_observations_raw_to_processed.py). Valid rows are upserted into raw.processed_fhir_observations
and rejected rows into raw.processed_fhir_observations_quarantine, each in one transaction inside the local Postgres
container. The batch is the full record of its encounters, so rows a regenerated batch no longer holds are removed.
split_groups.json becomes raw.patient_split_groups. A rerun leaves the same rows. Start the local stack first.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from string import Template
from typing import Any

from services.vital_signs import ANALYTICAL_VITAL_RANGES, FLATTENED_MEASUREMENTS, MEASUREMENT_NAMES
from tools.process import run_command

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "deploy" / "local" / "compose.yaml"
DEFAULT_BATCH = REPO_ROOT / "build" / "batch_vitals" / "seed-4817263_cohort-100"
RAW_SCHEMA = "raw"
# Load files are copied here inside the Postgres container, which the postgres user owns.
CONTAINER_LOAD_DIR = PurePosixPath("/var/lib/postgresql/local_load")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROCESSED_COLUMNS = (
    "observation_id",
    "patient_id",
    "encounter_id",
    "observation_type",
    "loinc_code",
    "value",
    "unit",
    "effective_datetime",
    "received_at",
    "source",
    "year",
    "month",
    "day",
)
# Postgres cannot bind identifiers as query parameters, so every name is checked against IDENTIFIER_PATTERN first.
PROCESSED_DDL = Template(
    "create table if not exists $schema.$table (observation_id text not null, patient_id text not null, encounter_id text, "
    "observation_type text, loinc_code text not null, value double precision, unit text, effective_datetime timestamptz, "
    "received_at timestamptz, source text, year integer, month integer, day integer, primary key (observation_id, loinc_code))"
)
UPSERT_SQL = Template(
    """begin;
create schema if not exists $schema;
$ddl;
create temporary table staged (like $schema.$table including defaults) on commit drop;
\\copy staged ($columns) from '$csv_path' with (format csv, header true)
insert into $schema.$table ($columns) select $columns from staged
on conflict (observation_id, loinc_code) do update set $updates
where $schema.$table.received_at is null or excluded.received_at >= $schema.$table.received_at;
delete from $schema.$table as current
where
    current.encounter_id in (select staged.encounter_id from staged)
    and not exists (
        select 1 from staged where staged.observation_id = current.observation_id and staged.loinc_code = current.loinc_code
    );
commit;"""
)
REPLACE_SQL = Template(
    """begin;
create schema if not exists $schema;
drop table if exists $schema.$table;
$ddl;
\\copy $schema.$table ($columns) from '$csv_path' with (format csv, header true)
commit;"""
)


def checked(*identifiers: str) -> None:
    for identifier in identifiers:
        if not IDENTIFIER_PATTERN.fullmatch(identifier):
            raise ValueError(f"unsafe SQL identifier: {identifier!r}")


def processed_rows(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
    """Split records into processed rows and (row, reason) rejections, keeping the latest row per observation and code."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    rejected: list[tuple[dict[str, Any], str]] = []
    for record in records:
        received_at = record.get("received_at") or record["event_timestamp"]
        for field_name, (loinc_code, unit) in FLATTENED_MEASUREMENTS.items():
            if record.get(field_name) is None:
                continue
            effective = datetime.fromisoformat(record["event_timestamp"])
            row = {
                "observation_id": record.get("observation_id") or "",
                "patient_id": record.get("patient_id") or "",
                "encounter_id": record.get("encounter_id"),
                "observation_type": MEASUREMENT_NAMES[loinc_code],
                "loinc_code": loinc_code,
                "value": float(record[field_name]),
                "unit": unit,
                "effective_datetime": record["event_timestamp"],
                "received_at": received_at,
                "source": record.get("source") or "fhir_webhook",
                "year": effective.year,
                "month": effective.month,
                "day": effective.day,
            }
            reason = rejection_reason(row, field_name)
            if reason:
                rejected.append((row, reason))
                continue
            key = (row["observation_id"], loinc_code)
            if key not in latest or row["received_at"] > latest[key]["received_at"]:
                latest[key] = row
    return list(latest.values()), rejected


def rejection_reason(row: dict[str, Any], field_name: str) -> str | None:
    """The Glue job's quality rule for one processed row, in the same order."""
    if not str(row["observation_id"]).strip():
        return "missing_observation_id"
    if not str(row["patient_id"]).strip():
        return "missing_patient_id"
    low, high = ANALYTICAL_VITAL_RANGES[field_name]
    if not low <= row["value"] <= high:
        return "physiological_range_violation"
    return None


def upsert_sql(schema: str, table: str, csv_path: PurePosixPath, columns: Sequence[str] = PROCESSED_COLUMNS) -> str:
    """One transaction: stage the CSV, insert new rows, update older or equally old ones (the Glue merge rule, with a tie
    going to this load, so a regenerated batch replaces its earlier values), then remove the
    batch encounters' rows that the CSV no longer holds."""
    checked(schema, table, *columns)
    updates = ", ".join(f"{name} = excluded.{name}" for name in columns if name not in ("observation_id", "loinc_code"))
    ddl = PROCESSED_DDL.substitute(schema=schema, table=table)
    return UPSERT_SQL.substitute(schema=schema, table=table, ddl=ddl, columns=", ".join(columns), updates=updates, csv_path=csv_path)


def replace_table_sql(schema: str, table: str, ddl: Template, csv_path: PurePosixPath, columns: Sequence[str]) -> str:
    """One transaction that recreates a small reference table from its DDL and the CSV, so added columns apply."""
    checked(schema, table, *columns)
    return REPLACE_SQL.substitute(schema=schema, table=table, ddl=ddl.substitute(schema=schema, table=table), columns=", ".join(columns), csv_path=csv_path)


def run_sql(sql: str, rows: list[dict[str, Any]], columns: Sequence[str], container_path: PurePosixPath) -> None:
    """Copy the rows into the Postgres container as CSV and run the statement there as the warehouse owner."""
    compose = ["compose", "-f", str(COMPOSE_FILE)]
    sql_path = container_path.with_suffix(".sql")
    run_command("docker", [*compose, "exec", "-T", "postgres", "mkdir", "-p", str(CONTAINER_LOAD_DIR)], timeout=60, check=True)
    with tempfile.TemporaryDirectory(prefix="local_warehouse_") as scratch:
        csv_file = Path(scratch) / "rows.csv"
        sql_file = Path(scratch) / "load.sql"
        with csv_file.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        sql_file.write_text(sql + "\n", encoding="utf-8")
        for local, remote in ((csv_file, container_path), (sql_file, sql_path)):
            run_command("docker", [*compose, "cp", str(local), f"postgres:{remote}"], timeout=300, check=True)
    result = run_command(
        "docker", [*compose, "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "warehouse", "-d", "warehouse", "-f", str(sql_path)], timeout=900
    )
    run_command("docker", [*compose, "exec", "-T", "postgres", "rm", "-f", str(container_path), str(sql_path)], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"the warehouse load failed and was rolled back: {result.stderr.strip()[-500:]}")


SPLIT_GROUP_DDL = Template("create table if not exists $schema.$table (patient_id text primary key, split_group text not null)")
QUARANTINE_COLUMNS = (*PROCESSED_COLUMNS, "rejection_reason")
QUARANTINE_DDL = Template(
    "create table if not exists $schema.$table (observation_id text, patient_id text, encounter_id text, observation_type text, "
    "loinc_code text, value double precision, unit text, effective_datetime timestamptz, received_at timestamptz, source text, "
    "year integer, month integer, day integer, rejection_reason text not null)"
)


def load_batch(folder: Path) -> dict[str, int]:
    """Load one batch folder into the local warehouse and return the row counts."""
    records = [json.loads(line) for path in sorted(folder.glob("*.ndjson")) for line in path.read_text(encoding="utf-8").splitlines()]
    rows, rejected = processed_rows(records)
    processed_csv = CONTAINER_LOAD_DIR / "processed.csv"
    run_sql(upsert_sql(RAW_SCHEMA, "processed_fhir_observations", processed_csv), rows, PROCESSED_COLUMNS, processed_csv)
    quarantine = [{**row, "rejection_reason": reason} for row, reason in rejected]
    quarantine_csv = CONTAINER_LOAD_DIR / "quarantine.csv"
    quarantine_sql = replace_table_sql(RAW_SCHEMA, "processed_fhir_observations_quarantine", QUARANTINE_DDL, quarantine_csv, QUARANTINE_COLUMNS)
    run_sql(quarantine_sql, quarantine, QUARANTINE_COLUMNS, quarantine_csv)
    groups = json.loads((folder / "split_groups.json").read_text(encoding="utf-8"))
    group_rows = [{"patient_id": patient_id, "split_group": group} for patient_id, group in sorted(groups.items())]
    groups_csv = CONTAINER_LOAD_DIR / "split_groups.csv"
    run_sql(
        replace_table_sql(RAW_SCHEMA, "patient_split_groups", SPLIT_GROUP_DDL, groups_csv, ("patient_id", "split_group")),
        group_rows,
        ("patient_id", "split_group"),
        groups_csv,
    )
    return {"records": len(records), "processed_rows": len(rows), "quarantined_rows": len(rejected), "split_groups": len(group_rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    args = parser.parse_args(argv)
    if not (args.batch / "manifest.json").is_file():
        parser.error(f"no batch at {args.batch}; run python -m jobs.batch_vitals.generate first")
    counts = load_batch(args.batch)
    sys.stdout.write(json.dumps(counts, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
