"""Merge a normalized NPPES snapshot into the dbt provider SCD2 seed."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path
from typing import Final

SNAPSHOT_FIELDS: Final = ("provider_npi", "provider_name", "taxonomy_code", "taxonomy_description", "provider_state")
HISTORY_FIELDS: Final = (*SNAPSHOT_FIELDS, "valid_from", "valid_to", "is_current", "data_source")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def _validate_fields(rows: list[dict[str, str]], required: tuple[str, ...], source: Path) -> None:
    missing = [field for field in required if not rows or field not in rows[0]]
    if missing:
        raise ValueError(f"{source} is missing required columns: {', '.join(missing)}")


def merge_provider_history(history: list[dict[str, str]], snapshot: list[dict[str, str]], effective_date: date) -> list[dict[str, str]]:
    """Close changed current rows and append new effective provider versions."""
    effective = effective_date.isoformat()
    current_by_npi = {row["provider_npi"]: row for row in history if row["is_current"].lower() == "true"}

    for provider in snapshot:
        npi = provider["provider_npi"]
        current = current_by_npi.get(npi)
        unchanged = current is not None and all(current[field] == provider[field] for field in SNAPSHOT_FIELDS)
        if unchanged:
            continue
        if current is not None:
            current["valid_to"] = effective
            current["is_current"] = "false"
        history.append(
            {
                **{field: provider[field] for field in SNAPSHOT_FIELDS},
                "valid_from": effective,
                "valid_to": "",
                "is_current": "true",
                "data_source": "nppes_snapshot",
            }
        )

    return sorted(history, key=lambda row: (row["provider_npi"], row["valid_from"]))


def update_provider_history(snapshot_path: Path, history_path: Path, output_path: Path, effective_date: date) -> None:
    snapshot = _read_csv(snapshot_path)
    history = _read_csv(history_path)
    _validate_fields(snapshot, SNAPSHOT_FIELDS, snapshot_path)
    _validate_fields(history, HISTORY_FIELDS, history_path)
    if len({row["provider_npi"] for row in snapshot}) != len(snapshot):
        raise ValueError(f"{snapshot_path} contains duplicate provider_npi values")

    merged = merge_provider_history(history, snapshot, effective_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(merged)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="Normalized current NPPES provider CSV")
    parser.add_argument("--history", type=Path, required=True, help="Existing provider history CSV")
    parser.add_argument("--output", type=Path, required=True, help="Destination provider history CSV")
    parser.add_argument("--effective-date", type=date.fromisoformat, required=True, help="Snapshot effective date in YYYY-MM-DD format")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    update_provider_history(args.snapshot, args.history, args.output, args.effective_date)


if __name__ == "__main__":
    main()
