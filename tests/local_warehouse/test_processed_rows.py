"""Batch records become the rows the AWS Glue job writes to the processed table (jobs/glue/fhir_observations_raw_to_processed.py).

Failure modes the local loader must handle (written before the loader):

1. A record carries two measurements (systolic and diastolic blood pressure): it becomes two rows sharing the observation ID.
2. A value outside the analytical range, a missing value or a missing patient: the row is quarantined, not loaded.
3. The same observation and code arrive twice: one row remains, the later received one (the Glue merge rule).
4. A rerun loads the same batch again: the table holds the same rows, with no duplicates.
5. The warehouse is unreachable or the load fails part way: the table keeps its previous rows (one transaction).
6. A regenerated batch moves an encounter's readings to new times and observation IDs: the encounter's rows from the
   earlier batch are removed in the same transaction, so only the new batch's rows remain (found by the end-to-end run).
7. A reference table gains a column: the replace recreates it from its DDL instead of copying into the old columns.

The local warehouse end-to-end run (python -m e2e.local_warehouse) proves the load against the real Postgres server.
"""

from __future__ import annotations

import pytest

from jobs.local_warehouse import load
from testkit import expect


def record(**fields) -> dict:
    base = {
        "schema_version": "1.1",
        "observation_id": "obs-1",
        "patient_id": "patient-1",
        "encounter_id": "encounter-1",
        "event_timestamp": "2026-09-01T08:00:05+00:00",
        "source": "batch_simulator",
    }
    return {**base, **fields}


def test_a_heart_rate_record_becomes_one_processed_row() -> None:
    rows, rejected = load.processed_rows([record(heart_rate=82.0)])

    expect.equal(rejected, [])
    expect.equal(
        rows,
        [
            {
                "observation_id": "obs-1",
                "patient_id": "patient-1",
                "encounter_id": "encounter-1",
                "observation_type": "heart_rate",
                "loinc_code": "8867-4",
                "value": 82.0,
                "unit": "beats/minute",
                "effective_datetime": "2026-09-01T08:00:05+00:00",
                "received_at": "2026-09-01T08:00:05+00:00",
                "source": "batch_simulator",
                "year": 2026,
                "month": 9,
                "day": 1,
            }
        ],
    )


def test_a_blood_pressure_record_becomes_two_rows_sharing_the_observation_id() -> None:
    rows, _ = load.processed_rows([record(systolic_bp=118.0, diastolic_bp=76.0)])

    expect.equal(sorted((row["observation_type"], row["value"]) for row in rows), [("diastolic_blood_pressure", 76.0), ("systolic_blood_pressure", 118.0)])
    expect.equal({row["observation_id"] for row in rows}, {"obs-1"})


def test_out_of_range_and_incomplete_rows_are_quarantined_with_a_reason() -> None:
    rows, rejected = load.processed_rows([record(heart_rate=300.0), record(observation_id="obs-2", patient_id="", heart_rate=80.0)])

    expect.equal(rows, [])
    expect.equal(sorted(reason for _, reason in rejected), ["missing_patient_id", "physiological_range_violation"])


def test_a_repeated_observation_keeps_the_later_received_row() -> None:
    first = record(heart_rate=80.0, received_at="2026-09-01T08:00:06+00:00")
    later = record(heart_rate=81.0, received_at="2026-09-01T08:00:09+00:00")

    rows, _ = load.processed_rows([later, first])

    expect.equal([row["value"] for row in rows], [81.0])


def test_the_load_statement_upserts_in_one_transaction() -> None:
    statement = load.upsert_sql("raw", "processed_fhir_observations", load.CONTAINER_LOAD_DIR / "rows.csv")

    for fragment in ("begin;", "on conflict (observation_id, loinc_code) do update", "excluded.received_at >", "commit;"):
        expect.is_in(fragment, statement.lower())


def test_unsafe_table_names_are_refused() -> None:
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        load.upsert_sql("raw", "observations; drop table x", load.CONTAINER_LOAD_DIR / "rows.csv")
