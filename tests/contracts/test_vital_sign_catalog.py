import ast
import json
from pathlib import Path

import yaml

from services.vital_signs import (
    ANALYTICAL_VITAL_RANGES,
    BLOOD_PRESSURE_PANEL_CODE,
    DIASTOLIC_CODE,
    FLATTENED_MEASUREMENTS,
    LOINC_VITAL_FIELDS,
    MEASUREMENT_NAMES,
    REALTIME_VITAL_RANGES,
    SUPPORTED_LOINC_CODES,
    SYSTOLIC_CODE,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "config/vital_signs.json").read_text())
VITALS = CATALOG["vital_signs"]


def imported_names(relative_path: str, module: str) -> set[str]:
    tree = ast.parse((ROOT / relative_path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return {name.name for name in node.names}
    raise AssertionError(f"Import from {module} was not found in {relative_path}")


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

    assert REALTIME_VITAL_RANGES == {field: tuple(vital["realtime_range"]) for field, vital in by_field.items()}
    assert LOINC_VITAL_FIELDS == {code_by_field[field]: field for field in ("heart_rate", "respiratory_rate", "spo2")}
    assert BLOOD_PRESSURE_PANEL_CODE == CATALOG["blood_pressure_panel"]["loinc_code"]
    assert SYSTOLIC_CODE == code_by_field["systolic_bp"]
    assert DIASTOLIC_CODE == code_by_field["diastolic_bp"]

    consumers = {
        "services/fhir_webhook/app/vitals.py": {"LOINC_VITAL_FIELDS", "BLOOD_PRESSURE_PANEL_CODE", "SYSTOLIC_CODE", "DIASTOLIC_CODE"},
        "services/vitals_simulator/app/fhir/observation.py": {"VITAL_SIGNS_BY_FIELD", "BLOOD_PRESSURE_PANEL"},
        "services/vitals_simulator/app/synthea/blood_pressure.py": {"BLOOD_PRESSURE_PANEL_CODE", "SYSTOLIC_CODE", "DIASTOLIC_CODE"},
    }
    for relative_path, expected_imports in consumers.items():
        assert expected_imports <= imported_names(relative_path, "services.vital_signs")
    assert 'import_module("services.vital_signs")' in (ROOT / "services/vitals_stream_processor/schema.py").read_text()


def test_glue_and_great_expectations_definitions_match_catalog() -> None:
    code_by_field = {vital["field"]: vital["loinc_code"] for vital in VITALS}
    expected_codes = set(code_by_field.values())

    assert MEASUREMENT_NAMES == {vital["loinc_code"]: vital["analytical_name"] for vital in VITALS}
    assert FLATTENED_MEASUREMENTS == {vital["field"]: (vital["loinc_code"], vital["unit"]) for vital in VITALS}
    assert ANALYTICAL_VITAL_RANGES == {vital["field"]: tuple(vital["analytical_range"]) for vital in VITALS}
    assert set(SUPPORTED_LOINC_CODES) == expected_codes
    assert {"ANALYTICAL_VITAL_RANGES", "FLATTENED_MEASUREMENTS", "MEASUREMENT_NAMES", "SUPPORTED_LOINC_CODES"} <= imported_names(
        "jobs/glue/fhir_observations_raw_to_processed.py", "services.vital_signs"
    )
    assert {"SUPPORTED_LOINC_CODES"} <= imported_names("data_quality/great_expectations/validate_processed_observations.py", "services.vital_signs")
    assert {"VITAL_SIGNS_BY_LOINC"} <= imported_names("scripts/quarantine/manage_quarantine.py", "services.vital_signs")


def test_dbt_and_soda_contracts_match_catalog() -> None:
    expected_codes = {vital["loinc_code"] for vital in VITALS}

    assert loinc_contract_values("dbt/models/staging/staging.yml") == expected_codes
    assert loinc_contract_values("data_quality/soda/contracts/stg_fhir_observations.yml") == expected_codes
    assert loinc_contract_values("data_quality/soda/contracts/dim_observation_type.yml") == expected_codes
