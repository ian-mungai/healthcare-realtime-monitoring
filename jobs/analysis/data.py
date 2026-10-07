"""The analysis frames from the local warehouse: one row per encounter and one per encounter and feature-window minute.

Each arm's warehouse (LOCAL_WAREHOUSE_SIGNAL, jobs.local_warehouse.load.warehouse_schemas) gives the analysis set of
the plan: training-eligible encounters with all seven NEWS2 parameters observed in the feature window. Systolic
pressure, temperature, inhaled oxygen and ACVPU are recorded every 5 minutes and are carried forward within an
encounter. Admitting diagnoses and attending specialties are grouped as the plan lists them. check_plan refuses a plan
whose SHA-256 differs from the frozen one. See plans/analysis-plan.md (local).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from string import Template

import pandas as pd

from jobs.calibration.features import FEATURE_COLUMNS
from jobs.local_warehouse import load
from services.vitals_simulator.app.fhir.admission import ADMITTING_DIAGNOSES
from tools.process import run_command

DIAGNOSIS_GROUPS = ("Cardiovascular", "Respiratory", "Infection and shock", "Other")
_DIAGNOSES = {
    "Cardiovascular": ("22298006", "401303003", "401314000", "88805009", "49436004", "132281000119108"),
    "Respiratory": ("233604007", "840539006", "389087006", "65710008", "195951007", "185086009", "87433001"),
    "Infection and shock": ("91302008", "770349000", "76571007", "27942005", "45816000", "128045006", "312157006"),
}
SPECIALTY_GROUPS = ("Critical care and pulmonary", "Cardiology", "Hospital and internal medicine", "Other")
_SPECIALTIES = {
    "207RC0200X": "Critical care and pulmonary",
    "207RP1001X": "Critical care and pulmonary",
    "207RC0000X": "Cardiology",
    "208M00000X": "Hospital and internal medicine",
    "207R00000X": "Hospital and internal medicine",
    "207RI0200X": "Other",
    "207RN0300X": "Other",
    "208600000X": "Other",
}
SLOPE_COLUMNS = ("heart_rate_slope", "respiratory_rate_slope", "spo2_slope", "systolic_bp_slope", "temperature_slope")
# Minute columns of fact_encounter_minute_features, renamed to the vitals' names.
MINUTE_COLUMNS = {
    "heart_rate_mean": "heart_rate",
    "respiratory_rate_mean": "respiratory_rate",
    "spo2_mean": "spo2",
    "systolic_bp_mean": "systolic_bp",
    "temperature_mean": "temperature",
    "inhaled_oxygen_concentration_max": "inhaled_oxygen_concentration",
    "consciousness_level_max": "consciousness_level",
}
FIVE_MINUTE_VITALS = ("systolic_bp", "temperature", "inhaled_oxygen_concentration", "consciousness_level")
MODERATORS = ("age_65_plus", "diagnosis_group", "specialty_group")
ENCOUNTERS_SQL = Template(
    "select training.encounter_key, training.patient_key, groups.split_group, training.deterioration_proxy_label as label, training.data_split, "
    "news2.news2_total, $features, $slopes, admissions.age_at_admission_years, admissions.diagnosis_code, admissions.attending_taxonomy_code "
    "from $analytics.ml_training_dataset as training "
    "inner join $analytics.fact_encounter_news2 as news2 on training.encounter_key = news2.encounter_key "
    "inner join $analytics.fact_encounter_trend_features as trends on training.encounter_key = trends.encounter_key "
    "inner join $analytics.fact_admissions as admissions on training.encounter_key = admissions.encounter_key "
    "inner join $raw.patient_split_groups as groups on training.patient_key = md5(groups.patient_id) "
    "order by training.encounter_key"
)
MINUTES_SQL = Template("select encounter_key, minute_index, $columns from $analytics.fact_encounter_minute_features order by encounter_key, minute_index")


class AnalysisError(RuntimeError):
    """The analysis cannot run on these inputs; the message names the input, never a patient."""


@dataclass(frozen=True)
class Frames:
    encounters: pd.DataFrame
    minutes: pd.DataFrame
    excluded_without_news2: int


def check_plan(path: Path, frozen_sha256: str) -> str:
    """The plan's SHA-256 when it equals the frozen one; otherwise stop before any data is read."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != frozen_sha256:
        raise AnalysisError(f"the analysis plan {path.name} changed since it was frozen (SHA-256 {digest[:12]}, frozen {frozen_sha256[:12]})")
    return digest


def diagnosis_group(code: str) -> str:
    for group, codes in _DIAGNOSES.items():
        if code in codes:
            return group
    if code in ADMITTING_DIAGNOSES:
        return "Other"
    raise AnalysisError(f"admitting diagnosis {code} is not on the admitting list")


def specialty_group(code: str) -> str:
    if code not in _SPECIALTIES:
        raise AnalysisError(f"attending taxonomy code {code} is not in the plan's specialty groups")
    return _SPECIALTIES[code]


def carry_forward(minutes: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """The minutes with each listed column carried forward within its encounter, never backward or across encounters."""
    ordered = minutes.sort_values(["encounter_key", "minute_index"]).copy()
    ordered[list(columns)] = ordered.groupby("encounter_key", sort=False)[list(columns)].ffill()
    return ordered.reset_index(drop=True)


def read_frame(sql: str, schemas: load.WarehouseSchemas) -> pd.DataFrame:
    """One read-only query in the arm's local warehouse schemas, as a frame."""
    load.checked(schemas.raw, schemas.analytics)
    statement = Template(sql).substitute(raw=schemas.raw, analytics=schemas.analytics)
    command = ["compose", "-f", str(load.COMPOSE_FILE), "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "warehouse", "-d", "warehouse"]
    command += ["-c", f"copy ({statement}) to stdout with (format csv, header)"]
    result = run_command("docker", command, timeout=600)
    if result.returncode != 0:
        raise AnalysisError(f"warehouse query failed: {result.stderr.strip()[-300:]}")
    return pd.read_csv(io.StringIO(result.stdout))


def load_frames(schemas: load.WarehouseSchemas) -> Frames:
    """The analysis set of one arm: encounters with a complete NEWS2, their minute rows and the moderators."""
    sql = ENCOUNTERS_SQL.safe_substitute(
        features=", ".join(f"training.{column}" for column in FEATURE_COLUMNS), slopes=", ".join(f"trends.{column}" for column in SLOPE_COLUMNS)
    )
    encounters = read_frame(sql, schemas)
    complete = encounters["news2_total"].notna()
    encounters = encounters[complete].reset_index(drop=True)
    encounters["age_65_plus"] = (encounters["age_at_admission_years"] >= 65).astype(int)
    encounters["diagnosis_group"] = encounters["diagnosis_code"].astype(str).map(diagnosis_group)
    encounters["specialty_group"] = encounters["attending_taxonomy_code"].map(specialty_group)
    minutes = read_frame(MINUTES_SQL.safe_substitute(columns=", ".join(MINUTE_COLUMNS)), schemas).rename(columns=MINUTE_COLUMNS)
    minutes = carry_forward(minutes, FIVE_MINUTE_VITALS)
    keep = ["encounter_key", "split_group", "label", *MODERATORS]
    minutes = minutes.merge(encounters[keep], on="encounter_key", how="inner")
    return Frames(encounters=encounters, minutes=minutes, excluded_without_news2=int((~complete).sum()))
