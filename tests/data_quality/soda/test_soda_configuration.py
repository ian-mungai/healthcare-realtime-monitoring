from pathlib import Path

import yaml

from testkit import expect

ROOT = Path(__file__).resolve().parents[3]

CONTRACTS_DIR = ROOT / "data_quality" / "soda" / "contracts"
EXAMPLE_CONFIG = ROOT / "data_quality" / "soda" / "config" / "configuration.example.yml"
DEPLOY_CONFIG = ROOT / "deploy" / "soda" / "configuration.yml"

EXPECTED_CONTRACT_FILES = {
    "dim_date.yml",
    "dim_encounter.yml",
    "dim_observation_type.yml",
    "dim_patient.yml",
    "dim_provider.yml",
    "fact_observations.yml",
    "fact_encounter_vital_features.yml",
    "ml_predictions_serving.yml",
    "ml_predictions_latest.yml",
    "ml_training_dataset.yml",
    "stg_fhir_observations.yml",
    # Cohort reference models, built on AWS since step 3b.4.
    "dim_patient_version.yml",
    "dim_facility.yml",
    "dim_unit.yml",
    "fact_admissions.yml",
    "fact_encounter_minute_features.yml",
}
REFERENCE_MODELS = ("dim_patient_version", "dim_facility", "dim_unit", "fact_admissions", "fact_encounter_minute_features")


def test_soda_contract_files_exist() -> None:
    contract_files = {path.name for path in CONTRACTS_DIR.glob("*.yml")}

    expect.equal(contract_files, EXPECTED_CONTRACT_FILES)


def test_soda_contract_files_are_valid_yaml() -> None:
    for path in CONTRACTS_DIR.glob("*.yml"):
        with path.open(encoding="utf-8") as file:
            contract = yaml.safe_load(file)

        expect.is_in("dataset", contract)
        expect.is_in("columns", contract)


def test_fact_contract_checks_compound_grain_uniqueness() -> None:
    with (CONTRACTS_DIR / "fact_observations.yml").open(encoding="utf-8") as file:
        contract = yaml.safe_load(file)

    duplicate_check = next(check["duplicate"] for check in contract["checks"] if "duplicate" in check)

    expect.equal(duplicate_check["columns"], ["observation_id", "loinc_code"])
    expect.equal(duplicate_check["threshold"]["must_be"], 0)


def test_soda_example_configuration_is_valid_yaml() -> None:
    with EXAMPLE_CONFIG.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)

    expect.equal(config["name"], "${env.SODA_DATA_SOURCE_NAME}")
    expect.equal(config["type"], "athena")
    expect.is_in("connection", config)


def test_soda_configurations_use_environment_namespace() -> None:
    for path in (EXAMPLE_CONFIG, DEPLOY_CONFIG):
        with path.open(encoding="utf-8") as file:
            config = yaml.safe_load(file)

        connection = config["connection"]
        expect.equal(connection["region_name"], "${env.AWS_REGION}")
        expect.equal(connection["staging_dir"], "s3://${env.DATA_BUCKET_NAME}/athena_results/soda/")
        expect.equal(connection["catalog"], "${env.ATHENA_CATALOG}")


def test_reference_model_contracts_name_the_model_and_its_documented_columns() -> None:
    models: dict[str, set[str]] = {}
    for path in (ROOT / "dbt/models/gold/core/core.yml", ROOT / "dbt/models/gold/analytics/analytics.yml"):
        models |= {model["name"]: {column["name"] for column in model.get("columns", [])} for model in yaml.safe_load(path.read_text())["models"]}

    for model in REFERENCE_MODELS:
        contract = yaml.safe_load((CONTRACTS_DIR / f"{model}.yml").read_text(encoding="utf-8"))
        expect.equal(contract["dataset"], f"${{env.SODA_DATA_SOURCE_NAME}}/${{env.ATHENA_CATALOG}}/${{env.ATHENA_DBT_DATABASE}}/{model}")
        expect.equal({column["name"] for column in contract["columns"]} - models[model], set())
