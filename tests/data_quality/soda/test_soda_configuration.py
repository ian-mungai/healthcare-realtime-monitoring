from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]

CONTRACTS_DIR = ROOT / "data_quality" / "soda" / "contracts"
EXAMPLE_CONFIG = ROOT / "data_quality" / "soda" / "config" / "configuration.example.yml"

EXPECTED_CONTRACT_FILES = {"dim_observation_type.yml", "dim_patient.yml", "fact_observations.yml", "stg_fhir_observations.yml"}


def test_soda_contract_files_exist() -> None:
    contract_files = {path.name for path in CONTRACTS_DIR.glob("*.yml")}

    assert contract_files == EXPECTED_CONTRACT_FILES


def test_soda_contract_files_are_valid_yaml() -> None:
    for path in CONTRACTS_DIR.glob("*.yml"):
        with path.open(encoding="utf-8") as file:
            contract = yaml.safe_load(file)

        assert "dataset" in contract
        assert "columns" in contract


def test_soda_example_configuration_is_valid_yaml() -> None:
    with EXAMPLE_CONFIG.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)

    assert config["name"] == "healthcare_realtime_athena"
    assert config["type"] == "athena"
    assert "connection" in config
