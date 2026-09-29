import ast
import json
import os
import sys
from pathlib import Path
from zipfile import ZipFile

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
from testkit import expect
from tools.process import run_command

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

    expect.equal(CATALOG["schema_version"], "1.0")
    if not (len(fields) == len(set(fields)) == 5):
        expect.fail("expected: len(fields) == len(set(fields)) == 5")
    if not (len(loinc_codes) == len(set(loinc_codes)) == 5):
        expect.fail("expected: len(loinc_codes) == len(set(loinc_codes)) == 5")


def test_catalog_loads_from_zipimport_runtime(tmp_path: Path) -> None:
    archive = tmp_path / "glue_dependencies.zip"
    members = ("config/__init__.py", "config/vital_signs.json", "services/__init__.py", "services/vital_signs.py")

    with ZipFile(archive, "w") as package:
        for member in members:
            package.write(ROOT / member, member)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(archive)
    probe = "from services.vital_signs import SUPPORTED_LOINC_CODES; print(len(SUPPORTED_LOINC_CODES))"
    result = run_command(sys.executable, ["-c", probe], cwd=tmp_path, env=environment, check=True)

    expect.equal(result.stdout.strip(), "5")


def test_python_service_definitions_match_catalog() -> None:
    by_field = {vital["field"]: vital for vital in VITALS}
    code_by_field = {field: vital["loinc_code"] for field, vital in by_field.items()}

    expect.equal({field: tuple(vital["realtime_range"]) for field, vital in by_field.items()}, REALTIME_VITAL_RANGES)
    expect.equal({code_by_field[field]: field for field in ("heart_rate", "respiratory_rate", "spo2")}, LOINC_VITAL_FIELDS)
    expect.equal(CATALOG["blood_pressure_panel"]["loinc_code"], BLOOD_PRESSURE_PANEL_CODE)
    expect.equal(code_by_field["systolic_bp"], SYSTOLIC_CODE)
    expect.equal(code_by_field["diastolic_bp"], DIASTOLIC_CODE)

    consumers = {
        "services/fhir_webhook/app/vitals.py": {"LOINC_VITAL_FIELDS", "BLOOD_PRESSURE_PANEL_CODE", "SYSTOLIC_CODE", "DIASTOLIC_CODE"},
        "services/vitals_simulator/app/fhir/observation.py": {"VITAL_SIGNS_BY_FIELD", "BLOOD_PRESSURE_PANEL"},
        "services/vitals_simulator/app/synthea/blood_pressure.py": {"BLOOD_PRESSURE_PANEL_CODE", "SYSTOLIC_CODE", "DIASTOLIC_CODE"},
    }
    for relative_path, expected_imports in consumers.items():
        if not (expected_imports <= imported_names(relative_path, "services.vital_signs")):
            expect.fail('expected: expected_imports <= imported_names(relative_path, "services.vital_signs")')
    expect.is_in('import_module("services.vital_signs")', (ROOT / "services/vitals_stream_processor/schema.py").read_text())


def test_glue_and_great_expectations_definitions_match_catalog() -> None:
    code_by_field = {vital["field"]: vital["loinc_code"] for vital in VITALS}
    expected_codes = set(code_by_field.values())

    expect.equal({vital["loinc_code"]: vital["analytical_name"] for vital in VITALS}, MEASUREMENT_NAMES)
    expect.equal({vital["field"]: (vital["loinc_code"], vital["unit"]) for vital in VITALS}, FLATTENED_MEASUREMENTS)
    expect.equal({vital["field"]: tuple(vital["analytical_range"]) for vital in VITALS}, ANALYTICAL_VITAL_RANGES)
    expect.equal(set(SUPPORTED_LOINC_CODES), expected_codes)
    if not (
        {"ANALYTICAL_VITAL_RANGES", "FLATTENED_MEASUREMENTS", "MEASUREMENT_NAMES", "SUPPORTED_LOINC_CODES"}
        <= imported_names("jobs/glue/fhir_observations_raw_to_processed.py", "services.vital_signs")
    ):
        expect.fail("the Glue job must import the shared vital-sign constants from services.vital_signs")
    if not ({"SUPPORTED_LOINC_CODES"} <= imported_names("data_quality/great_expectations/validate_processed_observations.py", "services.vital_signs")):
        expect.fail("the Great Expectations validator must import SUPPORTED_LOINC_CODES from services.vital_signs")
    if not ({"VITAL_SIGNS_BY_LOINC"} <= imported_names("scripts/quarantine/manage_quarantine.py", "services.vital_signs")):
        expect.fail('expected: {"VITAL_SIGNS_BY_LOINC"} <= imported_names("scripts/quarantine/manage_quarantine.py", "services.vital_signs")')


def test_dbt_and_soda_contracts_match_catalog() -> None:
    expected_codes = {vital["loinc_code"] for vital in VITALS}
    dbt_project = yaml.safe_load((ROOT / "dbt/dbt_project.yml").read_text())

    expect.equal(set(dbt_project["vars"]["vital_sign_loinc_codes"].values()), expected_codes)
    expect.equal(loinc_contract_values("dbt/models/silver/silver.yml"), expected_codes)
    expect.equal(loinc_contract_values("data_quality/soda/contracts/stg_fhir_observations.yml"), expected_codes)
    expect.equal(loinc_contract_values("data_quality/soda/contracts/dim_observation_type.yml"), expected_codes)

    feature_model = (ROOT / "dbt/models/gold/analytics/fact_encounter_vital_features.sql").read_text()
    expect.is_in("vital_sign_loinc_codes", feature_model)
    if expected_codes.intersection(feature_model.split("'")):
        expect.fail('expected: not expected_codes.intersection(feature_model.split("\'"))')
