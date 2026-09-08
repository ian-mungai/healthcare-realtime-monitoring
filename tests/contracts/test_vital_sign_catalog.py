import ast
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "config/vital_signs.json").read_text())
VITALS = CATALOG["vital_signs"]


def literal_assignment(relative_path: str, name: str) -> Any:
    tree = ast.parse((ROOT / relative_path).read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"Assignment {name} was not found in {relative_path}")


def loinc_contract_values(relative_path: str) -> set[str]:
    contract = yaml.safe_load((ROOT / relative_path).read_text())
    columns = contract["models"][0]["columns"] if "models" in contract else contract["columns"]
    loinc_column = next(column for column in columns if column["name"] == "loinc_code")
    checks = loinc_column.get("tests", loinc_column.get("checks", []))
    for check in checks:
        if "accepted_values" in check:
            return set(check["accepted_values"]["arguments"]["values"])
        if "invalid" in check:
            return set(check["invalid"]["valid_values"])
    raise AssertionError(f"LOINC accepted values were not found in {relative_path}")


def test_catalog_has_unique_fields_and_loinc_codes() -> None:
    fields = [vital["field"] for vital in VITALS]
    loinc_codes = [vital["loinc_code"] for vital in VITALS]

    assert CATALOG["schema_version"] == "1.0"
    assert len(fields) == len(set(fields)) == 5
    assert len(loinc_codes) == len(set(loinc_codes)) == 5


def test_python_service_definitions_match_catalog() -> None:
    by_field = {vital["field"]: vital for vital in VITALS}
    code_by_field = {field: vital["loinc_code"] for field, vital in by_field.items()}

    assert literal_assignment("services/vitals_stream_processor/schema.py", "VITAL_RANGES") == {
        field: tuple(vital["realtime_range"]) for field, vital in by_field.items()
    }
    assert literal_assignment("services/fhir_webhook/app/vitals.py", "LOINC_VITAL_FIELDS") == {
        code_by_field[field]: field for field in ("heart_rate", "respiratory_rate", "spo2")
    }
    assert literal_assignment("services/fhir_webhook/app/vitals.py", "BLOOD_PRESSURE_CODE") == CATALOG["blood_pressure_panel"]["loinc_code"]
    assert literal_assignment("services/fhir_webhook/app/vitals.py", "SYSTOLIC_CODE") == code_by_field["systolic_bp"]
    assert literal_assignment("services/fhir_webhook/app/vitals.py", "DIASTOLIC_CODE") == code_by_field["diastolic_bp"]
    assert literal_assignment("services/vitals_simulator/app/synthea/blood_pressure.py", "SYSTOLIC_CODE") == code_by_field["systolic_bp"]
    assert literal_assignment("services/vitals_simulator/app/synthea/blood_pressure.py", "DIASTOLIC_CODE") == code_by_field["diastolic_bp"]

    simulator_definitions = {
        "heart_rate": literal_assignment("services/vitals_simulator/app/fhir/observation.py", "HEART_RATE"),
        "respiratory_rate": literal_assignment("services/vitals_simulator/app/fhir/observation.py", "RESPIRATORY_RATE"),
        "spo2": literal_assignment("services/vitals_simulator/app/fhir/observation.py", "SPO2"),
        "systolic_bp": literal_assignment("services/vitals_simulator/app/fhir/observation.py", "SYSTOLIC_BP"),
        "diastolic_bp": literal_assignment("services/vitals_simulator/app/fhir/observation.py", "DIASTOLIC_BP"),
    }
    for field, definition in simulator_definitions.items():
        assert definition["loinc_code"] == by_field[field]["loinc_code"]
        assert definition["display"] == by_field[field]["display"]
        if "unit" in definition:
            assert definition["unit"] == by_field[field]["unit"]
            assert definition["ucum_code"] == by_field[field]["ucum_code"]


def test_glue_and_great_expectations_definitions_match_catalog() -> None:
    code_by_field = {vital["field"]: vital["loinc_code"] for vital in VITALS}
    expected_codes = set(code_by_field.values())

    assert literal_assignment("jobs/glue/fhir_observations_raw_to_processed.py", "MEASUREMENT_NAMES") == {
        vital["loinc_code"]: vital["analytical_name"] for vital in VITALS
    }
    assert literal_assignment("jobs/glue/fhir_observations_raw_to_processed.py", "FLATTENED_MEASUREMENTS") == {
        vital["field"]: (vital["loinc_code"], vital["unit"]) for vital in VITALS
    }
    assert literal_assignment("jobs/glue/fhir_observations_raw_to_processed.py", "ANALYTICAL_VITAL_RANGES") == {
        vital["field"]: tuple(vital["analytical_range"]) for vital in VITALS
    }
    assert set(literal_assignment("data_quality/great_expectations/validate_processed_observations.py", "VALID_LOINC_CODES")) == expected_codes


def test_dbt_and_soda_contracts_match_catalog() -> None:
    expected_codes = {vital["loinc_code"] for vital in VITALS}

    assert loinc_contract_values("dbt/models/staging/staging.yml") == expected_codes
    assert loinc_contract_values("data_quality/soda/contracts/stg_fhir_observations.yml") == expected_codes
    assert loinc_contract_values("data_quality/soda/contracts/dim_observation_type.yml") == expected_codes
