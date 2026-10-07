import csv
from pathlib import Path

import yaml

from services.vitals_simulator.app.fhir.admission import UNITS
from testkit import expect

ROOT = Path(__file__).resolve().parents[2]
CORE_MODELS = ROOT / "dbt/models/gold/core"
ANALYTICS_MODELS = ROOT / "dbt/models/gold/analytics"


def read_model(name: str) -> str:
    return (CORE_MODELS / f"{name}.sql").read_text()


def test_core_star_schema_models_exist() -> None:
    expected_models = {"dim_date.sql", "dim_encounter.sql", "dim_observation_type.sql", "dim_patient.sql", "dim_provider.sql", "fact_observations.sql"}
    # Built only when cohort_reference_enabled is true (docs/analytics-star-schema.md#cohort-reference-models).
    expected_models |= {"dim_facility.sql", "dim_patient_version.sql", "dim_unit.sql", "fact_admissions.sql"}

    expect.equal({path.name for path in CORE_MODELS.glob("*.sql")}, expected_models)


def test_fact_contains_stable_primary_and_foreign_keys() -> None:
    fact = read_model("fact_observations")

    for key in ("fact_observation_key", "patient_key", "encounter_key", "provider_version_key", "observation_type_key", "date_key"):
        expect.is_in(key, fact)


def test_encounters_require_real_active_cohort_context() -> None:
    encounter = read_model("dim_encounter")

    expect.not_in("__legacy_unknown__", encounter)
    expect.not_in("is_legacy_unknown", encounter)
    expect.is_in("concat('Encounter/', encounters.encounter_id)", encounter)


def test_dimensions_are_descriptive_not_observation_summaries() -> None:
    patient = read_model("dim_patient")
    observation_type = read_model("dim_observation_type")

    expect.not_in("observation_count", patient)
    expect.not_in("observation_row_count", patient)
    expect.not_in("observation_count", observation_type)
    expect.is_in("patient_reference", patient)
    expect.is_in("code_system", observation_type)


def test_core_contract_declares_fact_relationships() -> None:
    contract = yaml.safe_load((CORE_MODELS / "core.yml").read_text())
    fact = next(model for model in contract["models"] if model["name"] == "fact_observations")
    columns = {column["name"]: column for column in fact["columns"]}

    for key in ("patient_key", "encounter_key", "provider_version_key", "observation_type_key", "date_key"):
        if not any("relationships" in test for test in columns[key]["tests"]):
            expect.fail('expected: any("relationships" in test for test in columns[key]["tests"])')


def test_bus_matrix_documents_fact_grain_and_dimensions() -> None:
    bus_matrix = (ROOT / "docs/analytics-star-schema.md").read_text()

    expect.is_in("one vital-sign measurement per `observation_id` and `loinc_code`", bus_matrix)
    for dimension in ("DBT_DIM_PATIENT_TABLE", "DBT_DIM_ENCOUNTER_TABLE", "DBT_DIM_OBSERVATION_TYPE_TABLE", "DBT_DIM_DATE_TABLE", "DBT_DIM_PROVIDER_TABLE"):
        expect.is_in(dimension, bus_matrix)


def test_provider_dimension_declares_scd2_validity() -> None:
    provider = read_model("dim_provider")

    for column in ("provider_version_key", "provider_key", "valid_from", "valid_to", "is_current"):
        expect.is_in(column, provider)

    if not (ROOT / "dbt/tests/assert_dim_provider_single_current_version.sql").is_file():
        expect.fail('expected: (ROOT / "dbt/tests/assert_dim_provider_single_current_version.sql").is_file()')
    if not (ROOT / "dbt/tests/assert_dim_provider_non_overlapping_versions.sql").is_file():
        expect.fail('expected: (ROOT / "dbt/tests/assert_dim_provider_non_overlapping_versions.sql").is_file()')


def test_encounter_feature_model_separates_feature_and_outcome_windows() -> None:
    feature_model = (ANALYTICS_MODELS / "fact_encounter_vital_features.sql").read_text()

    expect.is_in("var('feature_window_minutes')", feature_model)
    expect.is_in("var('outcome_window_minutes')", feature_model)
    expect.not_in("date_diff('second', encounter_start_at, encounter_end_at)", feature_model)
    expect.is_in("is_feature_observation", feature_model)
    expect.is_in("is_outcome_observation", feature_model)
    expect.is_in("current_timestamp >= outcome_cutoff_at", feature_model)
    expect.is_in("deterioration_min_repeated_extreme_observations", feature_model)
    expect.is_in("outcome_systolic_bp_extreme_count", feature_model)
    expect.is_in("deterioration_proxy_label", feature_model)
    expect.is_in("news2-repeated-extreme-proxy-v2", feature_model)
    expect.is_in("label_definition_version", feature_model)


def test_ml_scoring_dataset_does_not_require_outcome_labels() -> None:
    scoring_model = (ANALYTICS_MODELS / "ml_scoring_dataset.sql").read_text()

    expect.is_in("where is_scoring_eligible", scoring_model)
    expect.not_in("deterioration_proxy_label", scoring_model)
    expect.not_in("data_split", scoring_model)
    expect.is_in("vital-features-v2", scoring_model)


def test_non_string_accepted_values_are_not_quoted() -> None:
    core_contract = yaml.safe_load((CORE_MODELS / "core.yml").read_text())
    analytics_contract = yaml.safe_load((ANALYTICS_MODELS / "analytics.yml").read_text())
    provider = next(model for model in core_contract["models"] if model["name"] == "dim_provider")
    features = next(model for model in analytics_contract["models"] if model["name"] == "fact_encounter_vital_features")

    for model, column_name in ((provider, "is_current"), (features, "deterioration_proxy_label")):
        column = next(column for column in model["columns"] if column["name"] == column_name)
        accepted_values = next(test["accepted_values"] for test in column["tests"] if "accepted_values" in test)
        expect.identical(accepted_values["arguments"]["quote"], False)


def test_ml_training_dataset_uses_patient_grouped_split() -> None:
    training_model = (ANALYTICS_MODELS / "ml_training_dataset.sql").read_text()
    class_readiness_test = (ROOT / "dbt/tests/assert_ml_training_dataset_has_both_classes.sql").read_text()

    expect.is_in("patient_key", training_model)
    expect.is_in("split_bucket", training_model)
    expect.is_in("< 8 then 'train'", training_model)
    expect.is_in("where is_training_eligible", training_model)
    if not (ROOT / "dbt/tests/assert_ml_training_dataset_no_patient_leakage.sql").is_file():
        expect.fail('expected: (ROOT / "dbt/tests/assert_ml_training_dataset_no_patient_leakage.sql").is_file()')
    if not (ROOT / "dbt/tests/assert_ml_training_dataset_has_both_splits.sql").is_file():
        expect.fail('expected: (ROOT / "dbt/tests/assert_ml_training_dataset_has_both_splits.sql").is_file()')
    if not (ROOT / "dbt/tests/assert_ml_training_dataset_has_both_classes.sql").is_file():
        expect.fail('expected: (ROOT / "dbt/tests/assert_ml_training_dataset_has_both_classes.sql").is_file()')
    expect.is_in("config(severity='warn')", class_readiness_test)


def test_latest_predictions_require_the_approved_model_version() -> None:
    latest_model = (ANALYTICS_MODELS / "ml_predictions_latest.sql").read_text()

    expect.is_in('env_var("ML_APPROVED_MODEL_VERSION")', latest_model)
    expect.not_in("order by max(scored_at)", latest_model)


def test_the_unit_seed_lists_every_simulator_unit_with_a_care_level() -> None:
    # A unit added to the simulator but not to the seed would leave admissions without a unit row.
    with (ROOT / "dbt/seeds/hospital_units.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    expect.equal(sorted(row["unit_name"] for row in rows), sorted(UNITS))
    expect.equal({row["care_level"] for row in rows}, {"critical", "intermediate", "acute"})
