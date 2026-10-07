"""Check the local warehouse end to end: load, reference extract, dbt build and the step 3 models, then write the report.

Usage: python -m e2e.local_warehouse [--batch DIRECTORY]

Run it after the local stack is started, the cohort is loaded and the batch is generated. It reads
COHORT_SIZE, FHIR_BASE_URL and FHIR_RESOURCE_MAP_FILE like the loader and the extract. The run loads the batch and the
cohort reference tables twice and checks that the second run leaves identical rows, builds every dbt model and test on
the local Postgres warehouse twice and checks that the training dataset is identical, then checks the admissions, the
patient versions, the record-grouped split and the 1-minute windows. Every run writes report.json and report.md under
artifacts/e2e/local_warehouse/, passed, failed or blocked.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from string import Template

from e2e.report import ROOT, Blocked, Report
from jobs.cohort_reference import extract
from jobs.local_warehouse import dbt, load
from services.vitals_simulator.app.fhir.admission import ADMITTING_DIAGNOSES
from tools.process import run_command

PURPOSE = "The local warehouse loads the batch and the cohort reference tables repeatably and dbt builds the step 3 models with every test passing."
LIMITS = (
    "Runs on the local Postgres warehouse only; the Athena SQL is compared by rendering, not run. The admissions, units and "
    "diagnoses are synthetic, planned by the simulator from each patient's Synthea record. No model is trained."
)
REPRODUCE = "Start the stack, load the cohort, generate the batch, then `.venv/bin/python -m e2e.local_warehouse`."
DBT_BUILD = ("build", "--exclude", "source:model_serving+")
# Each table's row count and an order-independent fingerprint of its rows.
# Table names are fixed in this file and checked against the loader's identifier pattern before use.
FINGERPRINT_SQL = Template(
    "select count(*), md5(coalesce(string_agg(md5(row_text), '' order by row_text), '')) "
    "from (select cast(t as text) as row_text from $schema.$table as t) as rows"
)
COUNT_SQL = Template("select count(*) from $schema.$table")
# Floating-point sums depend on the order Postgres reads rows, so the standard deviation can differ in the 15th
# significant digit between builds. The training fingerprint rounds every feature to 9 decimal places.
TRAINING_FEATURES = (
    "heart_rate_mean",
    "heart_rate_min",
    "heart_rate_max",
    "heart_rate_stddev",
    "respiratory_rate_mean",
    "respiratory_rate_min",
    "respiratory_rate_max",
    "spo2_mean",
    "spo2_min",
    "systolic_bp_mean",
    "systolic_bp_min",
    "diastolic_bp_mean",
)
TRAINING_FINGERPRINT_SQL = Template(
    "select count(*), md5(string_agg(row_text, '' order by row_text)) from (select concat_ws('|', encounter_key, patient_key, "
    "data_split, split_bucket, deterioration_proxy_label, $features) as row_text from analytics.ml_training_dataset) as rows"
)
MODEL_TABLES = ("dim_patient_version", "dim_facility", "dim_unit", "fact_admissions", "fact_encounter_minute_features", "ml_training_dataset")
RAW_TABLES = ("raw.processed_fhir_observations", "raw.patient_split_groups", *(f"raw.{name}" for name in extract.TABLES))
BATCH_ROWS_SQL = "select count(*) from raw.processed_fhir_observations where encounter_id in (select encounter_id from raw.admissions)"
CHECKS_SQL = {
    "admissions_without_version": "select count(*) from analytics.fact_admissions where patient_version_key is null",
    "admissions_raw": "select count(*) from raw.admissions",
    "admissions_fact": "select count(*) from analytics.fact_admissions",
    "patients_without_one_current_version": (
        "select count(*) from (select patient_id from analytics.dim_patient_version group by patient_id "
        "having sum(case when is_current then 1 else 0 end) <> 1) as patients"
    ),
    "split_groups_in_both_splits": (
        "select count(*) from (select groups.split_group from analytics.ml_training_dataset as training "
        "inner join raw.patient_split_groups as groups on training.patient_key = md5(groups.patient_id) "
        "group by groups.split_group having count(distinct training.data_split) > 1) as leaked"
    ),
    "splits_missing_a_class": (
        "select 2 - count(*) from (select data_split from analytics.ml_training_dataset group by data_split "
        "having count(distinct deterioration_proxy_label) = 2) as splits"
    ),
    # Synthea generates ages 18 to 90 on its run date; admissions fall within a month of it.
    "admissions_outside_adult_ages": "select count(*) from analytics.fact_admissions where age_at_admission_years < 18 or age_at_admission_years >= 91",
    "patients_65_and_over": "select count(distinct patient_key) from analytics.fact_admissions where age_at_admission_years >= 65",
    "encounters_without_15_minutes": (
        "select count(*) from (select training.encounter_key from analytics.ml_training_dataset as training "
        "left join analytics.fact_encounter_minute_features as minutes on training.encounter_key = minutes.encounter_key "
        "group by training.encounter_key having count(minutes.minute_index) <> 15) as short"
    ),
}


def query(sql: str) -> list[str]:
    """Run one read-only query in the local warehouse and return its rows as comma-separated text."""
    command = ["compose", "-f", str(load.COMPOSE_FILE), "exec", "-T", "postgres", "psql", "-U", "warehouse", "-d", "warehouse", "-At", "-F", ",", "-c", sql]
    result = run_command("docker", command, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"warehouse query failed: {result.stderr.strip()[-300:]}")
    return result.stdout.strip().splitlines()


def table_sql(template: Template, qualified: str) -> str:
    schema, table = qualified.split(".")
    load.checked(schema, table)
    return template.substitute(schema=schema, table=table)


def training_fingerprint() -> list[str]:
    load.checked(*TRAINING_FEATURES)
    return query(TRAINING_FINGERPRINT_SQL.substitute(features=", ".join(f"round(cast({name} as numeric), 9)" for name in TRAINING_FEATURES)))


def fingerprints(tables: tuple[str, ...]) -> dict[str, str]:
    return {table: query(table_sql(FINGERPRINT_SQL, table))[0] for table in tables}


def load_all(folder: Path) -> dict[str, int]:
    """Load the batch and extract the reference tables, keeping their JSON counts out of the report output."""
    counts = load.load_batch(folder)
    with contextlib.redirect_stdout(io.StringIO()) as output:
        extract.main([])
    return counts | json.loads(output.getvalue())


def check_loads(report: Report, folder: Path) -> None:
    counts = load_all(folder)
    first = fingerprints(RAW_TABLES)
    load_all(folder)
    second = fingerprints(RAW_TABLES)
    changed = [table for table in RAW_TABLES if first[table] != second[table]]
    report.check(
        "Batch and reference loads are repeatable", "a second run leaves identical rows in every raw table", f"{len(changed)} tables differ", not changed
    )
    # The raw table, like the data lake, also keeps rows of encounters outside this batch, such as an earlier cohort's.
    stored = int(query(BATCH_ROWS_SQL)[0])
    report.check(
        "Processed rows of the batch encounters match the batch",
        f"{counts['processed_rows']} rows, none left from an earlier batch",
        f"{stored}",
        stored == counts["processed_rows"],
    )
    report.check("No processed rows quarantined", "0", f"{counts['quarantined_rows']}", counts["quarantined_rows"] == 0)
    report.check(
        "Every admission extracted",
        "0 encounters without an admission",
        f"{counts['encounters_without_admission']}",
        counts["encounters_without_admission"] == 0,
    )
    report.evidence["raw_row_counts"] = {table: int(value.split(",")[0]) for table, value in second.items()}


def check_dbt(report: Report) -> None:
    first_code = dbt.main(list(DBT_BUILD))
    first = training_fingerprint()
    second_code = dbt.main(list(DBT_BUILD))
    second = training_fingerprint()
    report.check("dbt build passes twice", "exit code 0 both times", f"{first_code} and {second_code}", first_code == 0 and second_code == 0)
    report.check(
        "Training dataset is reproducible",
        "identical rows after the second build, features to 9 decimal places",
        "identical" if first == second else "differs",
        first == second,
    )


def check_models(report: Report) -> None:
    values = {name: int(query(sql)[0]) for name, sql in CHECKS_SQL.items()}
    report.check(
        "One admission row per extracted admission",
        f"{values['admissions_raw']}",
        f"{values['admissions_fact']}",
        values["admissions_raw"] == values["admissions_fact"],
    )
    report.check(
        "Every admission has the patient version valid at admission",
        "0 without",
        f"{values['admissions_without_version']}",
        values["admissions_without_version"] == 0,
    )
    report.check(
        "One current version per patient",
        "0 patients differ",
        f"{values['patients_without_one_current_version']}",
        values["patients_without_one_current_version"] == 0,
    )
    report.check("No waveform split group in both splits", "0 groups", f"{values['split_groups_in_both_splits']}", values["split_groups_in_both_splits"] == 0)
    report.check("Both splits hold both classes", "0 splits missing a class", f"{values['splits_missing_a_class']}", values["splits_missing_a_class"] == 0)
    report.check(
        "15 one-minute rows per training encounter",
        "0 encounters differ",
        f"{values['encounters_without_15_minutes']}",
        values["encounters_without_15_minutes"] == 0,
    )
    report.check(
        "Every admitted patient is an adult",
        "0 admissions outside ages 18 to 90",
        f"{values['admissions_outside_adult_ages']}",
        values["admissions_outside_adult_ages"] == 0,
    )
    report.evidence["patients_65_and_over"] = values["patients_65_and_over"]
    codes = set(query("select distinct diagnosis_code from analytics.fact_admissions"))
    report.check(
        "Every admitting diagnosis is on the admitting list", "0 other codes", f"{len(codes - set(ADMITTING_DIAGNOSES))}", codes <= set(ADMITTING_DIAGNOSES)
    )
    report.evidence["diagnosis_sources"] = dict(
        row.split(",") for row in query("select diagnosis_source, count(*) from analytics.fact_admissions group by diagnosis_source order by 1")
    )
    report.evidence["model_row_counts"] = {table: int(query(table_sql(COUNT_SQL, f"analytics.{table}"))[0]) for table in MODEL_TABLES}
    report.evidence["split_sizes"] = dict(
        row.split(",") for row in query("select data_split, count(*) from analytics.ml_training_dataset group by data_split order by 1")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--batch", type=Path, default=load.DEFAULT_BATCH)
    args = parser.parse_args(argv)
    report = Report(scenario="local_warehouse", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        if not (args.batch / "manifest.json").is_file():
            raise Blocked("the batch is missing; run python -m jobs.batch_vitals.generate first")
        if not dbt.DBT.is_file():
            raise Blocked("dbt-postgres is not installed; run .venv/bin/python -m tools.install_tools")
        report.parameters = {"batch": args.batch.name}
        check_loads(report, args.batch)
        check_dbt(report)
        check_models(report)
    except Exception as failure:
        error = failure
    report.finish(error)
    out = report.write()
    sys.stdout.write(f"local_warehouse: {report.status} ({out.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
