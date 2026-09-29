import sqlite3
from pathlib import Path

import yaml

from testkit import expect

ROOT = Path(__file__).resolve().parents[2]
DBT_TEST_PATH = ROOT / "dbt/tests/assert_fact_observations_unique_grain.sql"


def run_uniqueness_test(rows: list[tuple[str, str]]) -> list[tuple[str, str, int]]:
    query = DBT_TEST_PATH.read_text().replace("{{ ref('fact_observations') }}", "fact_observations")
    with sqlite3.connect(":memory:") as connection:
        connection.execute("create table fact_observations (observation_id text, loinc_code text)")
        connection.executemany("insert into fact_observations values (?, ?)", rows)
        return connection.execute(query).fetchall()


def test_fact_grain_test_passes_unique_measurements() -> None:
    rows = [("observation-1", "8867-4"), ("observation-1", "2708-6"), ("observation-2", "8867-4")]

    expect.equal(run_uniqueness_test(rows), [])


def test_fact_grain_test_returns_duplicate_measurements() -> None:
    rows = [("observation-1", "8867-4"), ("observation-1", "8867-4"), ("observation-1", "2708-6")]

    expect.equal(run_uniqueness_test(rows), [("observation-1", "8867-4", 2)])


def test_dbt_build_discovers_singular_tests() -> None:
    project = yaml.safe_load((ROOT / "dbt/dbt_project.yml").read_text())
    dockerfile = (ROOT / "deploy/dbt/Dockerfile").read_text()

    expect.equal(project["test-paths"], ["tests"])
    expect.is_in('CMD ["build", "--project-dir", "/app/dbt", "--profiles-dir", "/app"]', dockerfile)


def test_dbt_models_preserve_encounter_context() -> None:
    staging_model = (ROOT / "dbt/models/silver/stg_fhir_observations.sql").read_text()
    fact_model = (ROOT / "dbt/models/gold/core/fact_observations.sql").read_text()

    expect.is_in("encounter_id", staging_model)
    expect.is_in("encounter_id", fact_model)
    expect.is_in("ACTIVE_PATIENT_IDS", staging_model)
    expect.is_in("encounter_id is not null", staging_model)
    expect.not_in("__legacy_unknown__", fact_model)
