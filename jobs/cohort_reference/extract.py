"""Extract the warehouse's reference rows for the cohort: demographics, payer history, facilities and admissions.

Usage: python -m jobs.cohort_reference.extract

Demographics and payer history come from each cohort patient's Synthea bundle, facilities from Synthea's hospital file
and admissions from the simulator's encounters in HAPI FHIR. Rows keep no name, address line or other identifying
detail. The local run writes them to the raw schema of the local warehouse, each table in one transaction. It reads
COHORT_SIZE, FHIR_BASE_URL, FHIR_RESOURCE_MAP_FILE and LOCAL_WAREHOUSE_SIGNAL (study or null_control).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from string import Template
from typing import Any

import httpx

from scripts.synthea_loader.src.cohort import cohort_size
from scripts.synthea_loader.src.load_fhir import FHIR_OUTPUT_DIR, load_bundle
from services.vitals_simulator.app.bidmc.source import bidmc_source_for_position
from services.vitals_simulator.app.fhir.admission import FALLBACK_FACILITY
from services.vitals_simulator.app.fhir.attending import NPI_SYSTEM
from services.vitals_simulator.app.fhir.encounter import SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, SIMULATOR_SCENARIO_TAG_SYSTEM, is_null_control_run

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAP = REPO_ROOT / "build" / "local" / "fhir_resource_map.json"
NO_INSURANCE = "NO_INSURANCE"
RACE_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
ETHNICITY_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
PAGE_SIZE = 500

PATIENT_COLUMNS = ("patient_id", "birth_date", "gender", "race", "ethnicity", "marital_status", "state")
PAYER_COLUMNS = ("patient_id", "payer_name", "valid_from", "valid_to")
FACILITY_COLUMNS = ("facility_id", "facility_name", "city", "state")
ADMISSION_COLUMNS = (
    "encounter_id",
    "patient_id",
    "run_id",
    "scenario",
    "admitted_at",
    "discharged_at",
    "facility_id",
    "facility_name",
    "unit",
    "diagnosis_code",
    "diagnosis_display",
    "diagnosis_source",
    "attending_npi",
)
TABLES = {
    "fhir_patients": (PATIENT_COLUMNS, "patient_id text primary key, birth_date date, gender text, race text, ethnicity text, marital_status text, state text"),
    "patient_payer_history": (PAYER_COLUMNS, "patient_id text not null, payer_name text not null, valid_from date not null, valid_to date"),
    "facilities": (FACILITY_COLUMNS, "facility_id text primary key, facility_name text not null, city text, state text"),
    "admissions": (
        ADMISSION_COLUMNS,
        "encounter_id text primary key, patient_id text not null, run_id text not null, scenario text, admitted_at timestamptz not null, "
        "discharged_at timestamptz not null, facility_id text not null, facility_name text not null, unit text not null, "
        "diagnosis_code text not null, diagnosis_display text not null, diagnosis_source text, attending_npi text not null",
    ),
    # Written to S3 for AWS only; locally the batch's split_groups.json fills it (jobs.local_warehouse.load).
    "patient_split_groups": (("patient_id", "split_group"), "patient_id text primary key, split_group text not null"),
}


class ExtractError(RuntimeError):
    """The extract cannot run with these inputs; the message names the input, never an identifier."""


def bundles_for(cohort: dict[str, str], bundles: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Each cohort patient's (HAPI ID, Synthea bundle), in cohort order; stop on a missing bundle."""
    found = []
    for position, (synthea_id, hapi_id) in enumerate(cohort.items(), start=1):
        if synthea_id not in bundles:
            raise ExtractError(f"no Synthea bundle for cohort position {position}; regenerate the cohort")
        found.append((hapi_id, bundles[synthea_id]))
    return found


def resources(bundle: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    return [entry["resource"] for entry in bundle.get("entry", []) if entry.get("resource", {}).get("resourceType") == resource_type]


def extension_text(patient: dict[str, Any], url: str) -> str | None:
    for extension in patient.get("extension", []):
        if extension.get("url") == url:
            for part in extension.get("extension", []):
                if part.get("url") == "text":
                    return part.get("valueString")
    return None


def patient_rows(cohort: dict[str, str], bundles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for hapi_id, bundle in bundles_for(cohort, bundles):
        patient = resources(bundle, "Patient")[0]
        rows.append(
            {
                "patient_id": hapi_id,
                "birth_date": patient.get("birthDate"),
                "gender": patient.get("gender"),
                "race": extension_text(patient, RACE_URL),
                "ethnicity": extension_text(patient, ETHNICITY_URL),
                "marital_status": (patient.get("maritalStatus") or {}).get("text"),
                "state": ((patient.get("address") or [{}])[0]).get("state"),
            }
        )
    return rows


def payer_history_rows(cohort: dict[str, str], bundles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Payer periods per patient from their claims: a new period starts whenever the payer changes."""
    rows = []
    for hapi_id, bundle in bundles_for(cohort, bundles):
        claims = sorted(
            (claim.get("billablePeriod", {}).get("start", "")[:10], (claim.get("insurer") or {}).get("display") or NO_INSURANCE)
            for claim in resources(bundle, "ExplanationOfBenefit")
        )
        periods: list[dict[str, Any]] = []
        for start, payer in claims:
            if periods and periods[-1]["payer_name"] == payer:
                continue
            if periods:
                periods[-1]["valid_to"] = start
            periods.append({"patient_id": hapi_id, "payer_name": payer, "valid_from": start, "valid_to": None})
        rows += periods or [{"patient_id": hapi_id, "payer_name": NO_INSURANCE, "valid_from": "1900-01-01", "valid_to": None}]
    return rows


def facility_rows(hospital_bundle: dict[str, Any], facility_ids: set[str]) -> list[dict[str, Any]]:
    """The cohort's facilities from Synthea's hospital file, plus the simulator's fallback facility when used."""
    rows = []
    for organization in resources(hospital_bundle, "Organization"):
        if organization.get("id") in facility_ids:
            address = (organization.get("address") or [{}])[0]
            rows.append(
                {"facility_id": organization["id"], "facility_name": organization.get("name"), "city": address.get("city"), "state": address.get("state")}
            )
    if FALLBACK_FACILITY["id"] in facility_ids:
        rows.append({"facility_id": FALLBACK_FACILITY["id"], "facility_name": FALLBACK_FACILITY["name"], "city": None, "state": None})
    return rows


def admission_rows(base_url: str, patient_ids: set[str], signal: str = "study") -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Every cohort patient's simulator encounter of this signal that carries an admission, read page by page; return the
    rows and the skipped counts: encounters without admission fields, of patients outside the cohort and of the other
    signal (the study's warehouse skips the null control's encounters and the other way round)."""
    rows: list[dict[str, Any]] = []
    skipped = {"without_admission": 0, "outside_cohort": 0, "other_signal": 0}
    url: str | None = f"{base_url.rstrip('/')}/Encounter"
    params: dict[str, Any] | None = {"identifier": f"{SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM}|", "_count": PAGE_SIZE}
    with httpx.Client(headers={"Accept": "application/fhir+json"}, timeout=60) as client:
        while url:
            page = client.get(url, params=params).raise_for_status().json()
            for entry in page.get("entry", []):
                row = admission_row(entry["resource"])
                if row is None:
                    skipped["without_admission"] += 1
                elif row["patient_id"] not in patient_ids:
                    skipped["outside_cohort"] += 1
                elif is_null_control_run(row["run_id"]) != (signal == "null_control"):
                    skipped["other_signal"] += 1
                else:
                    rows.append(row)
            url = next((link["url"] for link in page.get("link", []) if link.get("relation") == "next"), None)
            params = None
    return rows, skipped


def admission_row(encounter: dict[str, Any]) -> dict[str, Any] | None:
    period = encounter.get("period", {})
    reason_code = (encounter.get("reasonCode") or [{}])[0]
    reason = (reason_code.get("coding") or [{}])[0]
    provider = encounter.get("serviceProvider") or {}
    unit = ((encounter.get("location") or [{}])[0].get("location") or {}).get("display")
    attending_npi = attending(encounter)
    if not (period.get("end") and reason.get("code") and provider.get("display") and unit and attending_npi):
        return None
    identifier = next(item["value"] for item in encounter.get("identifier", []) if item.get("system") == SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM)
    scenario = next((tag["code"] for tag in encounter.get("meta", {}).get("tag", []) if tag.get("system") == SIMULATOR_SCENARIO_TAG_SYSTEM), None)
    return {
        "encounter_id": encounter["id"],
        "patient_id": encounter["subject"]["reference"].removeprefix("Patient/"),
        "run_id": identifier.split(":", 1)[0],
        "scenario": scenario,
        "admitted_at": period["start"],
        "discharged_at": period["end"],
        "facility_id": (provider.get("identifier") or {}).get("value"),
        "facility_name": provider["display"],
        "unit": unit,
        "diagnosis_code": reason["code"],
        "diagnosis_display": reason.get("display"),
        "diagnosis_source": reason_code.get("text"),
        "attending_npi": attending_npi,
    }


def attending(encounter: dict[str, Any]) -> str | None:
    """The NPI of the encounter's attending participant; the display name stays in HAPI."""
    for participant in encounter.get("participant", []):
        codes = {coding.get("code") for kind in participant.get("type", []) for coding in kind.get("coding", [])}
        identifier = (participant.get("individual") or {}).get("identifier") or {}
        if "ATND" in codes and identifier.get("system") == NPI_SYSTEM:
            return identifier.get("value")
    return None


def split_group_rows(cohort: dict[str, str]) -> list[dict[str, str]]:
    """Each patient's waveform split group, from their cohort position as the simulator assigns records."""
    rows = []
    for position, hapi_id in enumerate(cohort.values(), start=1):
        record_number, _epoch = bidmc_source_for_position(position)
        rows.append({"patient_id": hapi_id, "split_group": f"bidmc{record_number:02d}"})
    return rows


def read_bundles(directory: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """The Synthea patient bundles by Synthea patient ID, and the hospital bundle, from one output folder."""
    bundles = {}
    hospital: dict[str, Any] | None = None
    for path in sorted(directory.glob("*.json")):
        bundle = load_bundle(path)
        if path.name.startswith("hospitalInformation"):
            hospital = bundle
        elif resources(bundle, "Patient"):
            bundles[resources(bundle, "Patient")[0]["id"]] = bundle
    if hospital is None:
        raise ExtractError("no Synthea hospitalInformation file; regenerate the cohort")
    return bundles, hospital


def build_tables(
    resource_map: dict[str, Any], bundles: dict[str, dict[str, Any]], hospital: dict[str, Any], base_url: str, signal: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """The reference tables for one signal's encounters, and the encounters skipped by reason."""
    entries = resource_map["cohort"]
    if len(entries) != cohort_size():
        raise ExtractError(f"the resource map holds {len(entries)} patients but COHORT_SIZE is {cohort_size()}")
    cohort = {synthea_id: entry["hapi_patient_id"] for synthea_id, entry in sorted(entries.items())}
    facility_ids = {facility["id"] for entry in entries.values() for facility in (entry.get("admission_profile") or {}).get("facilities", [])}
    admissions, skipped = admission_rows(base_url, set(cohort.values()), signal)
    facility_ids |= {row["facility_id"] for row in admissions}
    tables = {
        "fhir_patients": patient_rows(cohort, bundles),
        "patient_payer_history": payer_history_rows(cohort, bundles),
        "facilities": facility_rows(hospital, facility_ids),
        "admissions": admissions,
        "patient_split_groups": split_group_rows(cohort),
    }
    return tables, skipped


def json_lines(rows: list[dict[str, Any]]) -> bytes:
    """One JSON object per line with sorted keys, the format the Glue reference tables read."""
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")


def write_s3(tables: dict[str, list[dict[str, Any]]], s3: Any, bucket: str, prefix: str) -> None:
    """Replace each reference table on AWS: one object per table at a fixed key, so a rerun leaves no earlier rows."""
    for table, rows in tables.items():
        key = f"{prefix.rstrip('/')}/{table}/{table}.json"
        s3.put_object(Bucket=bucket, Key=key, Body=json_lines(rows), ServerSideEncryption="AES256", ContentType="application/x-ndjson")


def write_local(tables: dict[str, list[dict[str, Any]]], schema: str) -> None:
    """Replace each raw reference table in the selected signal's raw schema, one transaction per table."""
    from jobs.local_warehouse import load

    for table, rows in tables.items():
        columns, column_sql = TABLES[table]
        ddl = Template("create table if not exists $schema.$table (" + column_sql + ")")
        csv_path = load.CONTAINER_LOAD_DIR / f"{table}.csv"
        load.run_sql(load.replace_table_sql(schema, table, ddl, csv_path, columns), rows, columns, csv_path)


def main(argv: list[str] | None = None) -> int:
    del argv
    from jobs.local_warehouse import load

    map_file = Path(os.getenv("FHIR_RESOURCE_MAP_FILE") or DEFAULT_MAP)
    resource_map = json.loads(map_file.read_text(encoding="utf-8"))
    bundles, hospital = read_bundles(FHIR_OUTPUT_DIR)
    schemas = load.warehouse_schemas()
    tables, skipped = build_tables(resource_map, bundles, hospital, os.getenv("FHIR_BASE_URL") or "http://127.0.0.1:8080/fhir", schemas.signal)
    # Locally the split groups come from the batch (jobs.local_warehouse.load), so they are not written here.
    tables.pop("patient_split_groups")
    write_local(tables, schemas.raw)
    counts = {table: len(rows) for table, rows in tables.items()} | {f"encounters_{reason}": count for reason, count in skipped.items()}
    sys.stdout.write(json.dumps(counts, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
