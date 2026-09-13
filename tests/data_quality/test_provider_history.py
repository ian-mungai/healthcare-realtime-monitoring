import csv
from datetime import date
from pathlib import Path

from scripts.nppes.update_provider_history import merge_provider_history, update_provider_history


def current_provider(npi: str, taxonomy_code: str = "207R00000X") -> dict[str, str]:
    return {
        "provider_npi": npi,
        "provider_name": "Example Provider",
        "taxonomy_code": taxonomy_code,
        "taxonomy_description": "Internal Medicine",
        "provider_state": "MA",
        "valid_from": "2024-01-01",
        "valid_to": "",
        "is_current": "true",
        "data_source": "nppes_snapshot",
    }


def test_changed_provider_closes_current_version_and_appends_successor() -> None:
    history = [current_provider("1999000013")]
    snapshot = [
        {
            key: value
            for key, value in current_provider("1999000013", "207RC0000X").items()
            if key in {"provider_npi", "provider_name", "taxonomy_code", "taxonomy_description", "provider_state"}
        }
    ]

    merged = merge_provider_history(history, snapshot, date(2025, 1, 1))

    assert len(merged) == 2
    assert merged[0]["valid_to"] == "2025-01-01"
    assert merged[0]["is_current"] == "false"
    assert merged[1]["taxonomy_code"] == "207RC0000X"
    assert merged[1]["is_current"] == "true"


def test_unchanged_provider_does_not_create_a_new_version() -> None:
    provider = current_provider("1999000013")
    snapshot = [{key: provider[key] for key in ("provider_npi", "provider_name", "taxonomy_code", "taxonomy_description", "provider_state")}]

    assert merge_provider_history([provider], snapshot, date(2025, 1, 1)) == [provider]


def test_update_rejects_duplicate_snapshot_npis(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.csv"
    history_path = tmp_path / "history.csv"
    output_path = tmp_path / "output.csv"
    snapshot_fields = ("provider_npi", "provider_name", "taxonomy_code", "taxonomy_description", "provider_state")
    provider = current_provider("1999000013")

    with snapshot_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=snapshot_fields)
        writer.writeheader()
        writer.writerows([{field: provider[field] for field in snapshot_fields}] * 2)
    with history_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=provider)
        writer.writeheader()
        writer.writerow(provider)

    try:
        update_provider_history(snapshot_path, history_path, output_path, date(2025, 1, 1))
    except ValueError as error:
        assert "duplicate provider_npi" in str(error)
    else:
        raise AssertionError("duplicate provider_npi values must fail")
