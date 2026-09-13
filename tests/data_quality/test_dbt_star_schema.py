from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CORE_MODELS = ROOT / "dbt/models/marts/core"
ANALYTICS_MODELS = ROOT / "dbt/models/marts/analytics"


def read_model(name: str) -> str:
    return (CORE_MODELS / f"{name}.sql").read_text()


def test_core_star_schema_models_exist() -> None:
    expected_models = {"dim_date.sql", "dim_encounter.sql", "dim_observation_type.sql", "dim_patient.sql", "dim_provider.sql", "fact_observations.sql"}

    assert {path.name for path in CORE_MODELS.glob("*.sql")} == expected_models


def test_fact_contains_stable_primary_and_foreign_keys() -> None:
    fact = read_model("fact_observations")

    for key in ("fact_observation_key", "patient_key", "encounter_key", "provider_version_key", "observation_type_key", "date_key"):
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

    for key in ("patient_key", "encounter_key", "provider_version_key", "observation_type_key", "date_key"):
        assert any("relationships" in test for test in columns[key]["tests"])


def test_bus_matrix_documents_fact_grain_and_dimensions() -> None:
    bus_matrix = (ROOT / "docs/analytics-star-schema.md").read_text()

    assert "one vital-sign measurement per `observation_id` and `loinc_code`" in bus_matrix
    for dimension in ("dim_patient", "dim_encounter", "dim_observation_type", "dim_date", "dim_provider"):
        assert dimension in bus_matrix


def test_provider_dimension_declares_scd2_validity() -> None:
    provider = read_model("dim_provider")

    for column in ("provider_version_key", "provider_key", "valid_from", "valid_to", "is_current"):
        assert column in provider

    assert (ROOT / "dbt/tests/assert_dim_provider_single_current_version.sql").is_file()
    assert (ROOT / "dbt/tests/assert_dim_provider_non_overlapping_versions.sql").is_file()


def test_encounter_feature_model_separates_feature_and_outcome_windows() -> None:
    feature_model = (ANALYTICS_MODELS / "fct_encounter_vital_features.sql").read_text()

    assert "* 0.8" in feature_model
    assert "is_feature_observation" in feature_model
    assert "is_outcome_observation" in feature_model
    assert "deterioration_proxy_label" in feature_model
    assert "label_definition_version" in feature_model


def test_non_string_accepted_values_are_not_quoted() -> None:
    core_contract = yaml.safe_load((CORE_MODELS / "core.yml").read_text())
    analytics_contract = yaml.safe_load((ANALYTICS_MODELS / "analytics.yml").read_text())
    provider = next(model for model in core_contract["models"] if model["name"] == "dim_provider")
    features = next(model for model in analytics_contract["models"] if model["name"] == "fct_encounter_vital_features")

    for model, column_name in ((provider, "is_current"), (features, "deterioration_proxy_label")):
        column = next(column for column in model["columns"] if column["name"] == column_name)
        accepted_values = next(test["accepted_values"] for test in column["tests"] if "accepted_values" in test)
        assert accepted_values["arguments"]["quote"] is False
