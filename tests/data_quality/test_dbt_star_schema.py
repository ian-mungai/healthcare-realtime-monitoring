from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CORE_MODELS = ROOT / "dbt/models/marts/core"


def read_model(name: str) -> str:
    return (CORE_MODELS / f"{name}.sql").read_text()


def test_core_star_schema_models_exist() -> None:
    expected_models = {"dim_date.sql", "dim_encounter.sql", "dim_observation_type.sql", "dim_patient.sql", "fact_observations.sql"}

    assert {path.name for path in CORE_MODELS.glob("*.sql")} == expected_models


def test_fact_contains_stable_primary_and_foreign_keys() -> None:
    fact = read_model("fact_observations")

    for key in ("fact_observation_key", "patient_key", "encounter_key", "observation_type_key", "date_key"):
        assert key in fact


def test_dimensions_are_descriptive_not_observation_summaries() -> None:
    patient = read_model("dim_patient")
    observation_type = read_model("dim_observation_type")

    assert "observation_count" not in patient
    assert "observation_row_count" not in patient
    assert "observation_count" not in observation_type
    assert "patient_reference" in patient
    assert "code_system" in observation_type


def test_core_contract_declares_fact_relationships() -> None:
    contract = yaml.safe_load((CORE_MODELS / "core.yml").read_text())
    fact = next(model for model in contract["models"] if model["name"] == "fact_observations")
    columns = {column["name"]: column for column in fact["columns"]}

    for key in ("patient_key", "encounter_key", "observation_type_key", "date_key"):
        assert any("relationships" in test for test in columns[key]["tests"])


def test_bus_matrix_documents_fact_grain_and_dimensions() -> None:
    bus_matrix = (ROOT / "docs/analytics-star-schema.md").read_text()

    assert "one vital-sign measurement per `observation_id` and `loinc_code`" in bus_matrix
    for dimension in ("dim_patient", "dim_encounter", "dim_observation_type", "dim_date"):
        assert dimension in bus_matrix
