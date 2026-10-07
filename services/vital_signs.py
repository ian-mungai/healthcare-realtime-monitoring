import json
from importlib.resources import files
from pathlib import Path
from typing import Any


def _catalog_text() -> str:
    try:
        return files("config").joinpath("vital_signs.json").read_text(encoding="utf-8")
    except (ModuleNotFoundError, OSError, TypeError):
        pass

    candidates = (Path(__file__).resolve().parents[1] / "config" / "vital_signs.json", Path(__file__).resolve().parent / "config" / "vital_signs.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise RuntimeError("Vital-sign catalog is not packaged with this runtime")


CATALOG: dict[str, Any] = json.loads(_catalog_text())
VITAL_SIGNS: tuple[dict[str, Any], ...] = tuple(CATALOG["vital_signs"])
VITAL_SIGNS_BY_FIELD = {vital["field"]: vital for vital in VITAL_SIGNS}
VITAL_SIGNS_BY_LOINC = {vital["loinc_code"]: vital for vital in VITAL_SIGNS}

BLOOD_PRESSURE_PANEL = CATALOG["blood_pressure_panel"]
BLOOD_PRESSURE_PANEL_CODE = BLOOD_PRESSURE_PANEL["loinc_code"]
SYSTOLIC_CODE = VITAL_SIGNS_BY_FIELD["systolic_bp"]["loinc_code"]
DIASTOLIC_CODE = VITAL_SIGNS_BY_FIELD["diastolic_bp"]["loinc_code"]

VITAL_FIELDS = tuple(vital["field"] for vital in VITAL_SIGNS)
# Single-value quantity Observations; blood pressure arrives as components of its panel instead.
LOINC_VITAL_FIELDS = {
    vital["loinc_code"]: vital["field"]
    for vital in VITAL_SIGNS
    if vital.get("value_type", "quantity") == "quantity" and vital["loinc_code"] not in (SYSTOLIC_CODE, DIASTOLIC_CODE)
}
# Coded Observations (ACVPU): the answer code maps to an ordinal, which the event carries as a number.
CODED_VITAL_FIELDS = {vital["loinc_code"]: vital["field"] for vital in VITAL_SIGNS if vital.get("value_type") == "coded"}
ANSWER_ORDINALS = {
    vital["field"]: {answer["code"]: answer["ordinal"] for answer in vital["answers"]} for vital in VITAL_SIGNS if vital.get("value_type") == "coded"
}
ORDINAL_FIELDS = tuple(ANSWER_ORDINALS)
MEASUREMENT_NAMES = {vital["loinc_code"]: vital["analytical_name"] for vital in VITAL_SIGNS}
FLATTENED_MEASUREMENTS = {vital["field"]: (vital["loinc_code"], vital["unit"]) for vital in VITAL_SIGNS}
REALTIME_VITAL_RANGES = {vital["field"]: tuple(vital["realtime_range"]) for vital in VITAL_SIGNS}
ANALYTICAL_VITAL_RANGES = {vital["field"]: tuple(vital["analytical_range"]) for vital in VITAL_SIGNS}
SUPPORTED_LOINC_CODES = tuple(VITAL_SIGNS_BY_LOINC)
