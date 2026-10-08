"""Check the local warehouse end to end: load, reference extract, dbt build and the step 3 models, then write the report.

Usage: python -m e2e.local_warehouse [--batch DIRECTORY]

Run it after the local stack is started, the cohort is loaded and the batch is generated. It reads
COHORT_SIZE, FHIR_BASE_URL and FHIR_RESOURCE_MAP_FILE like the loader and the extract. The run loads the batch and the
cohort reference tables twice and checks that the second run leaves identical rows, builds every dbt model and test on
the local Postgres warehouse, loads the batch again and builds again, and checks that every row of the feature tables
is identical to the last digit, then checks the admissions, the
patient versions, the record-grouped split and the 1-minute windows. Every run writes report.json and report.md under
artifacts/e2e/local_warehouse/, passed, failed or blocked.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import statistics
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from string import Template

from e2e.report import ROOT, Blocked, Report
from jobs.calibration.features import FEATURE_COLUMNS, encounter_features
from jobs.cohort_reference import extract
from jobs.local_warehouse import dbt, load
from services.vitals_simulator.app.fhir.admission import ADMITTING_DIAGNOSES
from services.vitals_simulator.app.fhir.attending import UNIT_SPECIALTIES
from services.vitals_simulator.app.simulation.scenario import FEATURE_WINDOW_SECONDS
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
# The analysis models read these tables. Every float feature must repeat to the last digit after the batch is loaded
# again, because gradient-boosted trees bin on exact values: a difference in the 15th significant digit changed its AUC.
FEATURE_TABLES = ("ml_training_dataset", "fact_encounter_trend_features", "fact_encounter_minute_features")
MODEL_TABLES = ("dim_patient_version", "dim_facility", "dim_unit", "fact_admissions", "fact_encounter_minute_features", "ml_training_dataset")
RAW_TABLE_NAMES = ("processed_fhir_observations", "patient_split_groups", *extract.TABLES)
# The signal's schemas (LOCAL_WAREHOUSE_SIGNAL); every SQL string names them as $raw and $analytics.
SCHEMAS = load.warehouse_schemas("study")
BATCH_VALUE_SUMS_SQL = (
    "select loinc_code, round(cast(sum(value) as numeric), 3) from $raw.processed_fhir_observations "
    "where encounter_id in (select encounter_id from $raw.admissions) group by loinc_code order by loinc_code"
)
ADMISSION_HOURS_SQL = "select facility_id, unit, admitted_at, discharged_at from $raw.admissions"
CENSUS_SQL = "select unit_key, to_char(hour_start, 'YYYY-MM-DD HH24:MI'), census, admissions, discharges from $analytics.fact_unit_hourly_census"
NEWS2_SQL = "select encounter_key, coalesce(cast(news2_total as varchar), '') from $analytics.fact_encounter_news2 order by encounter_key"
TREND_FIELDS = ("heart_rate", "respiratory_rate", "spo2", "systolic_bp", "temperature")
TRENDS_SQL = Template("select encounter_key, $columns from $$analytics.fact_encounter_trend_features order by encounter_key")
CALIBRATION_FEATURES_SQL = Template("select encounter_key, $columns from $$analytics.ml_training_dataset order by encounter_key")
BATCH_ROWS_SQL = "select count(*) from $raw.processed_fhir_observations where encounter_id in (select encounter_id from $raw.admissions)"
CHECKS_SQL = {
    "admissions_without_version": "select count(*) from $analytics.fact_admissions where patient_version_key is null",
    "admissions_raw": "select count(*) from $raw.admissions",
    "admissions_without_attending_version": "select count(*) from $analytics.fact_admissions where provider_version_key is null",
    "attendings_outside_washington": (
        "select count(*) from $analytics.fact_admissions as admissions inner join $analytics.dim_provider as providers "
        "on admissions.provider_version_key = providers.provider_version_key where providers.provider_state <> 'WA'"
    ),
    "admitted_encounters_with_placeholder_provider": (
        "select count(*) from $analytics.dim_encounter where is_synthetic_provider_assignment and encounter_id in (select encounter_id from $raw.admissions)"
    ),
    "admissions_fact": "select count(*) from $analytics.fact_admissions",
    "patients_without_one_current_version": (
        "select count(*) from (select patient_id from $analytics.dim_patient_version group by patient_id "
        "having sum(case when is_current then 1 else 0 end) <> 1) as patients"
    ),
    "split_groups_in_both_splits": (
        "select count(*) from (select groups.split_group from $analytics.ml_training_dataset as training "
        "inner join $raw.patient_split_groups as groups on training.patient_key = md5(groups.patient_id) "
        "group by groups.split_group having count(distinct training.data_split) > 1) as leaked"
    ),
    "splits_missing_a_class": (
        "select 2 - count(*) from (select data_split from $analytics.ml_training_dataset group by data_split "
        "having count(distinct deterioration_proxy_label) = 2) as splits"
    ),
    # Synthea generates ages 18 to 90 on its run date; admissions fall within a month of it.
    "admissions_outside_adult_ages": "select count(*) from $analytics.fact_admissions where age_at_admission_years < 18 or age_at_admission_years >= 91",
    "patients_65_and_over": "select count(distinct patient_key) from $analytics.fact_admissions where age_at_admission_years >= 65",
    "training_rows": "select count(*) from $analytics.ml_training_dataset",
    "training_rows_without_bedside_features": (
        "select count(*) from $analytics.ml_training_dataset "
        "where temperature_mean is null or inhaled_oxygen_concentration_max is null or consciousness_level_max is null"
    ),
    "encounters_without_15_minutes": (
        "select count(*) from (select training.encounter_key from $analytics.ml_training_dataset as training "
        "left join $analytics.fact_encounter_minute_features as minutes on training.encounter_key = minutes.encounter_key "
        "group by training.encounter_key having count(minutes.minute_index) <> 15) as short"
    ),
}


def query(sql: str) -> list[str]:
    """Run one read-only query in the local warehouse and return its rows as comma-separated text."""
    load.checked(SCHEMAS.raw, SCHEMAS.analytics)
    sql = Template(sql).safe_substitute(raw=SCHEMAS.raw, analytics=SCHEMAS.analytics)
    command = ["compose", "-f", str(load.COMPOSE_FILE), "exec", "-T", "postgres", "psql", "-U", "warehouse", "-d", "warehouse", "-At", "-F", ",", "-c", sql]
    result = run_command("docker", command, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"warehouse query failed: {result.stderr.strip()[-300:]}")
    return result.stdout.strip().splitlines()


def raw_tables() -> tuple[str, ...]:
    return tuple(f"{SCHEMAS.raw}.{name}" for name in RAW_TABLE_NAMES)


def table_sql(template: Template, qualified: str) -> str:
    schema, table = qualified.split(".")
    load.checked(schema, table)
    return template.substitute(schema=schema, table=table)


def feature_fingerprints() -> dict[str, str]:
    """Each feature table's row count and the fingerprint of its rows as text, which keeps every digit of a float."""
    return {table: query(table_sql(FINGERPRINT_SQL, f"{SCHEMAS.analytics}.{table}"))[0] for table in FEATURE_TABLES}


def fingerprints(tables: tuple[str, ...]) -> dict[str, str]:
    return {table: query(table_sql(FINGERPRINT_SQL, table))[0] for table in tables}


def load_all(folder: Path) -> dict[str, int]:
    """Load the batch and extract the reference tables, keeping their JSON counts out of the report output."""
    counts = load.load_batch(folder, SCHEMAS.raw)
    with contextlib.redirect_stdout(io.StringIO()) as output:
        extract.main([])
    return counts | json.loads(output.getvalue())


def batch_value_sums(folder: Path) -> dict[str, Decimal]:
    """The sum of each measurement's values in the batch, after the Glue rules, rounded like the warehouse query."""
    records = [json.loads(line) for path in sorted(folder.glob("*.ndjson")) for line in path.read_text(encoding="utf-8").splitlines()]
    sums: dict[str, Decimal] = {}
    for row in load.processed_rows(records)[0]:
        sums[row["loinc_code"]] = sums.get(row["loinc_code"], Decimal(0)) + Decimal(str(row["value"]))
    return {code: total.quantize(Decimal("0.001")) for code, total in sums.items()}


def check_loads(report: Report, folder: Path) -> None:
    counts = load_all(folder)
    first = fingerprints(raw_tables())
    load_all(folder)
    second = fingerprints(raw_tables())
    changed = [table for table in raw_tables() if first[table] != second[table]]
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
    expected_sums = batch_value_sums(folder)
    stored_sums = {code: Decimal(total) for code, total in (row.split(",") for row in query(BATCH_VALUE_SUMS_SQL))}
    differing = sorted(code for code in expected_sums.keys() | stored_sums.keys() if expected_sums.get(code) != stored_sums.get(code))
    report.check(
        "Stored values match the batch for every measurement",
        "the sum of values per LOINC code equals the batch's",
        f"{len(differing)} codes differ" + (f": {', '.join(differing)}" if differing else ""),
        not differing,
    )
    report.check("No processed rows quarantined", "0", f"{counts['quarantined_rows']}", counts["quarantined_rows"] == 0)
    report.check(
        "Every admission extracted",
        "0 encounters without an admission",
        f"{counts['encounters_without_admission']}",
        counts["encounters_without_admission"] == 0,
    )
    report.evidence["raw_row_counts"] = {table: int(value.split(",")[0]) for table, value in second.items()}


def check_dbt(report: Report, folder: Path) -> None:
    """Build, load the batch again and build again: the reload stores the rows in another physical order."""
    first_code = dbt.main(list(DBT_BUILD))
    first = feature_fingerprints()
    load_all(folder)
    second_code = dbt.main(list(DBT_BUILD))
    second = feature_fingerprints()
    report.check("dbt build passes twice", "exit code 0 both times", f"{first_code} and {second_code}", first_code == 0 and second_code == 0)
    changed = [table for table in FEATURE_TABLES if first[table] != second[table]]
    report.check(
        "Features are reproducible after a reload",
        "identical rows to the last digit in every feature table after loading the batch again and rebuilding",
        f"{len(changed)} tables differ" + (f": {', '.join(changed)}" if changed else ""),
        not changed,
    )


def check_calibration_features(report: Report, folder: Path) -> None:
    """The calibration job's Python features equal the warehouse's v3 features for every encounter of the batch.

    Only feature columns are compared; labels and model scores are not read.
    """
    by_encounter = batch_records(folder)
    rows = query(CALIBRATION_FEATURES_SQL.safe_substitute(columns=", ".join(FEATURE_COLUMNS)))
    differing = 0
    for row in rows:
        key, *stored = row.split(",")
        expected = encounter_features(by_encounter.get(key, []))
        for column, value in zip(FEATURE_COLUMNS, stored, strict=True):
            wanted = expected[column]
            if (value == "") != (wanted is None) or (wanted is not None and abs(float(value) - wanted) > 1e-6):
                differing += 1
                break
    report.check(
        "Calibration features match the warehouse",
        f"all {len(FEATURE_COLUMNS)} v3 features of every training encounter",
        f"{differing} of {len(rows)} encounters differ",
        differing == 0 and len(rows) > 0,
    )


def minute_slopes(records: list[dict]) -> dict[str, float | None]:
    """Per vital, the least-squares slope of the feature window's minute means over the minute index, from batch records."""
    timed = sorted(((datetime.fromisoformat(record["event_timestamp"]), record) for record in records), key=lambda pair: pair[0])
    if not timed:
        return dict.fromkeys(TREND_FIELDS)
    start = timed[0][0]
    minutes: dict[str, dict[int, list[float]]] = {field: {} for field in TREND_FIELDS}
    for when, record in timed:
        elapsed = (when - start).total_seconds()
        if elapsed >= FEATURE_WINDOW_SECONDS:
            continue
        for field in TREND_FIELDS:
            if record.get(field) is not None:
                minutes[field].setdefault(int(elapsed // 60), []).append(float(record[field]))
    slopes: dict[str, float | None] = {}
    for field, by_minute in minutes.items():
        points = sorted((minute, sum(values) / len(values)) for minute, values in by_minute.items())
        slopes[field] = statistics.linear_regression([x for x, _ in points], [y for _, y in points]).slope if len(points) > 1 else None
    return slopes


def check_news2_and_trends(report: Report, folder: Path) -> None:
    """The warehouse's feature-window NEWS2 and trend slopes equal an independent Python computation from the batch records."""
    by_encounter = batch_records(folder)
    news2_rows = query(NEWS2_SQL)
    news2_differ = 0
    for row in news2_rows:
        key, total = row.split(",")
        wanted = encounter_features(by_encounter.get(key, []))["news2"]
        news2_differ += int((total == "") != (wanted is None) or (wanted is not None and int(total) != wanted))
    report.check(
        "Warehouse NEWS2 matches services/news2.py",
        "every encounter's feature-window NEWS2 equal, missing where a parameter is missing",
        f"{news2_differ} of {len(news2_rows)} encounters differ",
        news2_differ == 0 and len(news2_rows) > 0,
    )
    report.evidence["news2_missing"] = sum(1 for row in news2_rows if row.endswith(","))
    trend_rows = query(TRENDS_SQL.safe_substitute(columns=", ".join(f"coalesce(cast({field}_slope as varchar), '')" for field in TREND_FIELDS)))
    trend_differ = 0
    for row in trend_rows:
        key, *stored = row.split(",")
        wanted = minute_slopes(by_encounter.get(key, []))
        for field, value in zip(TREND_FIELDS, stored, strict=True):
            expected = wanted[field]
            if (value == "") != (expected is None) or (expected is not None and abs(float(value) - expected) > 1e-6):
                trend_differ += 1
                break
    report.check(
        "Warehouse trend slopes match the minute means",
        f"all {len(TREND_FIELDS)} slopes of every training encounter",
        f"{trend_differ} of {len(trend_rows)} encounters differ",
        trend_differ == 0 and len(trend_rows) > 0,
    )


def expected_census() -> dict[tuple[str, str], tuple[int, int, int]]:
    """Per unit and UTC hour, the admissions present at any time in that hour and those admitted and discharged in it."""
    counts: dict[tuple[str, str], list[int]] = {}
    for row in query(ADMISSION_HOURS_SQL):
        facility_id, unit, admitted_text, discharged_text = row.split(",")
        admitted = datetime.fromisoformat(admitted_text).astimezone(UTC)
        discharged = datetime.fromisoformat(discharged_text).astimezone(UTC)
        unit_key = hashlib.md5(f"{facility_id}|{unit}".encode(), usedforsecurity=False).hexdigest()
        hour = admitted.replace(minute=0, second=0, microsecond=0)
        while hour < discharged:
            cell = counts.setdefault((unit_key, hour.strftime("%Y-%m-%d %H:%M")), [0, 0, 0])
            cell[0] += 1
            cell[1] += int(hour <= admitted < hour + timedelta(hours=1))
            cell[2] += int(hour <= discharged < hour + timedelta(hours=1))
            hour += timedelta(hours=1)
    return {key: (present, admitted, discharged) for key, (present, admitted, discharged) in counts.items()}


def check_census(report: Report) -> None:
    """The hourly census equals a count from the raw admissions, hour by hour and unit by unit."""
    expected = expected_census()
    stored = {}
    for row in query(CENSUS_SQL):
        unit_key, hour, census, admitted, discharged = row.split(",")
        stored[(unit_key, hour)] = (int(census), int(admitted), int(discharged))
    differing = sum(1 for key in expected.keys() | stored.keys() if expected.get(key) != stored.get(key))
    report.check(
        "Hourly census matches the admissions",
        f"{len(expected)} unit hours with census, admissions and discharges equal",
        f"{differing} of {len(expected | stored)} unit hours differ",
        differing == 0 and len(stored) > 0,
    )
    report.evidence["census_unit_hours"] = len(stored)
    report.evidence["census_peak"] = max((values[0] for values in stored.values()), default=0)


def batch_records(folder: Path) -> dict[str, list[dict]]:
    """The batch's records by encounter key (the warehouse's MD5 of the encounter ID)."""
    by_encounter: dict[str, list[dict]] = {}
    for path in sorted(folder.glob("*.ndjson")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            by_encounter.setdefault(hashlib.md5(record["encounter_id"].encode(), usedforsecurity=False).hexdigest(), []).append(record)
    return by_encounter


def check_models(report: Report, folder: Path) -> None:
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
    encounters = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["encounters"]
    report.check(
        "Admissions are the loaded batch's encounters",
        f"{encounters} admissions, none from the null control or another batch",
        f"{values['admissions_fact']}",
        values["admissions_fact"] == encounters,
    )
    report.check(
        "Every batch encounter reaches the training set",
        f"{encounters} training rows, one per finished stay",
        f"{values['training_rows']}",
        values["training_rows"] == encounters,
    )
    report.check(
        "Every training encounter has temperature, inhaled oxygen and ACVPU features",
        "0 rows without them",
        f"{values['training_rows_without_bedside_features']}",
        values["training_rows_without_bedside_features"] == 0,
    )
    report.check(
        "Every admitted patient is an adult",
        "0 admissions outside ages 18 to 90",
        f"{values['admissions_outside_adult_ages']}",
        values["admissions_outside_adult_ages"] == 0,
    )
    report.check(
        "Every admission has the attending version valid at admission",
        "0 without",
        f"{values['admissions_without_attending_version']}",
        values["admissions_without_attending_version"] == 0,
    )
    report.check(
        "Every attending practises in Washington on the admission date",
        "0 outside",
        f"{values['attendings_outside_washington']}",
        values["attendings_outside_washington"] == 0,
    )
    pairs = {tuple(row.split(",")) for row in query("select distinct unit, attending_taxonomy_code from $analytics.fact_admissions")}
    outside = sorted(f"{unit}: {code}" for unit, code in pairs if code not in UNIT_SPECIALTIES.get(unit, ()))
    report.check("Every attending's specialty covers the unit", "0 unit and specialty pairs outside the rule", f"{len(outside)} {outside}", not outside)
    report.check(
        "Admitted encounters carry their attending, not a placeholder",
        "0 placeholders",
        f"{values['admitted_encounters_with_placeholder_provider']}",
        values["admitted_encounters_with_placeholder_provider"] == 0,
    )
    report.evidence["attending_specialties_by_scenario"] = [
        row.split(",") for row in query("select scenario, attending_specialty, count(*) from $analytics.fact_admissions group by 1, 2 order by 1, 2")
    ]
    report.evidence["attendings"] = int(query("select count(distinct provider_key) from $analytics.fact_admissions")[0])
    report.evidence["patients_65_and_over"] = values["patients_65_and_over"]
    codes = set(query("select distinct diagnosis_code from $analytics.fact_admissions"))
    report.check(
        "Every admitting diagnosis is on the admitting list", "0 other codes", f"{len(codes - set(ADMITTING_DIAGNOSES))}", codes <= set(ADMITTING_DIAGNOSES)
    )
    report.evidence["diagnosis_sources"] = dict(
        row.split(",") for row in query("select diagnosis_source, count(*) from $analytics.fact_admissions group by diagnosis_source order by 1")
    )
    report.evidence["model_row_counts"] = {table: int(query(table_sql(COUNT_SQL, f"{SCHEMAS.analytics}.{table}"))[0]) for table in MODEL_TABLES}
    report.evidence["split_sizes"] = dict(
        row.split(",") for row in query("select data_split, count(*) from $analytics.ml_training_dataset group by data_split order by 1")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--batch", type=Path, default=None, help="defaults to the batch of LOCAL_WAREHOUSE_SIGNAL (study)")
    args = parser.parse_args(argv)
    global SCHEMAS
    SCHEMAS = load.warehouse_schemas()
    args.batch = args.batch or SCHEMAS.batch
    report = Report(scenario="local_warehouse", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        if not (args.batch / "manifest.json").is_file():
            raise Blocked("the batch is missing; run python -m jobs.batch_vitals.generate first")
        if not dbt.DBT.is_file():
            raise Blocked("dbt-postgres is not installed; run .venv/bin/python -m tools.install_tools")
        report.parameters = {"batch": args.batch.name, "signal": SCHEMAS.signal, "schemas": f"{SCHEMAS.raw}, {SCHEMAS.analytics}"}
        check_loads(report, args.batch)
        check_dbt(report, args.batch)
        check_models(report, args.batch)
        check_calibration_features(report, args.batch)
        check_news2_and_trends(report, args.batch)
        check_census(report)
    except Exception as failure:
        error = failure
    report.finish(error)
    out = report.write()
    sys.stdout.write(f"local_warehouse: {report.status} ({out.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
