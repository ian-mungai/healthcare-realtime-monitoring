"""Check the local 100-patient cohort and its batch vitals end to end and write the report.

Usage: python -m e2e.local_cohort [--batch DIRECTORY]

Run it after the local stack is started, the cohort is loaded into local HAPI FHIR and the batch is generated. It reads COHORT_SIZE, FHIR_BASE_URL and FHIR_RESOURCE_MAP_FILE like the generator. The run checks
that every cohort patient exists in HAPI with exactly one normal and one deterioration batch encounter, that the
manifest and files agree, that every record passes the stream processor's schema and follows its scenario in the
outcome window, and that a second generation run reuses the encounters and writes identical files. Every run writes
report.json and report.md under artifacts/e2e/local_cohort/, passed, failed or blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

from e2e.report import ROOT, Blocked, Report
from jobs.batch_vitals import generate
from scripts.synthea_loader.src.cohort import cohort_patient_ids, cohort_size
from services.vitals_simulator.app.fhir.encounter import SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, SIMULATOR_SCENARIO_TAG_SYSTEM
from services.vitals_simulator.app.simulation.scenario import DETERIORATION_SCENARIO, FEATURE_WINDOW_SECONDS, NORMAL_SCENARIO
from services.vitals_stream_processor.schema import validate_vitals_payload

DEFAULT_MAP = ROOT / "build" / "local" / "fhir_resource_map.json"
PURPOSE = "Every local cohort patient has a normal and a deterioration batch encounter whose records the stream processor accepts."
LIMITS = (
    "Checks the local HAPI server and the batch files only; it does not stream the batch, run dbt or train a model. Patients past "
    "the 53 waveform records reuse a record from another start point, so the 100 patients are not fully independent."
)
REPRODUCE = "Start the stack, load the cohort, generate the batch, then `.venv/bin/python -m e2e.local_cohort`."
# Outcome-window values set by services/vitals_simulator/app/simulation/scenario.py.
DETERIORATION_VALUES = {"heart_rate": 135.0, "respiratory_rate": 28.0, "spo2": 89.0}
NORMAL_RANGES = {"heart_rate": (50.0, 100.0), "respiratory_rate": (12.0, 20.0), "spo2": (95.0, 100.0)}


def batch_encounters(client: httpx.Client, seed: str, patient_id: str) -> list[dict]:
    """The batch encounters HAPI holds for one patient, one search per run identifier."""
    found = []
    for run in range(1, generate.RUNS_PER_PATIENT + 1):
        value = f"batch-{seed}-{run}:{patient_id}"
        bundle = client.get("/Encounter", params={"identifier": f"{SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM}|{value}"}).raise_for_status().json()
        found += [entry["resource"] for entry in bundle.get("entry", [])]
    return found


def check_hapi(report: Report, base_url: str, patient_ids: tuple[str, ...], seed: str) -> dict[str, str]:
    """Check patients and batch encounters in HAPI; return each batch encounter ID with its scenario."""
    missing_patients, wrong_encounters = 0, 0
    scenarios: dict[str, str] = {}
    with httpx.Client(base_url=base_url, headers={"Accept": "application/fhir+json"}, timeout=30) as client:
        for patient_id in patient_ids:
            if client.get(f"/Patient/{patient_id}").status_code != 200:
                missing_patients += 1
            encounters = batch_encounters(client, seed, patient_id)
            tags = sorted(
                tag["code"]
                for encounter in encounters
                for tag in encounter.get("meta", {}).get("tag", [])
                if tag.get("system") == SIMULATOR_SCENARIO_TAG_SYSTEM
            )
            if tags != [DETERIORATION_SCENARIO, NORMAL_SCENARIO]:
                wrong_encounters += 1
            for encounter in encounters:
                scenarios[encounter["id"]] = next(tag["code"] for tag in encounter["meta"]["tag"] if tag["system"] == SIMULATOR_SCENARIO_TAG_SYSTEM)
    report.check("Cohort patients in HAPI", f"all {len(patient_ids)} present", f"{missing_patients} missing", missing_patients == 0)
    report.check("One normal and one deterioration batch encounter per patient", "every patient", f"{wrong_encounters} patients differ", wrong_encounters == 0)
    return scenarios


def check_files(report: Report, folder: Path, patient_ids: tuple[str, ...], scenarios: dict[str, str]) -> bytes:
    manifest_bytes = (folder / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    expected = {"cohort_size": len(patient_ids), "encounters": 2 * len(patient_ids)}
    observed = {name: manifest.get(name) for name in expected}
    report.check("Manifest size", f"{expected}", f"{observed}", observed == expected)
    counts = manifest.get("scenario_counts", {})
    report.check(
        "Scenario balance", f"{len(patient_ids)} of each", f"{counts}", counts == {DETERIORATION_SCENARIO: len(patient_ids), NORMAL_SCENARIO: len(patient_ids)}
    )
    bad_hashes = invalid = off_scenario = wrong_encounter = 0
    observation_ids: set[str] = set()
    records = 0
    for entry in manifest["files"]:
        content = (folder / entry["name"]).read_bytes()
        bad_hashes += hashlib.sha256(content).hexdigest() != entry["sha256"]
        started = datetime.fromisoformat(entry["started_at"])
        for line in content.decode("utf-8").splitlines():
            record = json.loads(line)
            records += 1
            observation_ids.add(record["observation_id"])
            try:
                validate_vitals_payload(record)
            except ValueError:
                invalid += 1
            wrong_encounter += scenarios.get(record["encounter_id"]) != entry["scenario"]
            if (datetime.fromisoformat(record["event_timestamp"]) - started).total_seconds() >= FEATURE_WINDOW_SECONDS:
                off_scenario += not follows_scenario(record, entry["scenario"])
    report.check("File checksums", "all match the manifest", f"{bad_hashes} differ", bad_hashes == 0)
    report.check("Records accepted by the stream processor schema", f"all {records}", f"{invalid} rejected", invalid == 0 and records == manifest["records"])
    report.check("Observation IDs unique", f"{records} unique", f"{len(observation_ids)} unique", len(observation_ids) == records)
    report.check("Records belong to the HAPI encounter of their scenario", "all", f"{wrong_encounter} differ", wrong_encounter == 0)
    report.check("Outcome window follows the scenario", "all outcome-window records", f"{off_scenario} differ", off_scenario == 0)
    rejected = sum(manifest.get("rejected_records", {}).values())
    report.check(
        "Waveform dropouts left out",
        "at most 1% of records",
        f"{rejected} ({rejected / max(records + rejected, 1):.2%})",
        rejected <= 0.01 * (records + rejected),
    )
    report.evidence = {
        "records": records,
        "rejected_records": manifest.get("rejected_records", {}),
        "scenario_counts": counts,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    return manifest_bytes


def follows_scenario(record: dict, scenario: str) -> bool:
    for name, value in DETERIORATION_VALUES.items():
        if name in record:
            if scenario == DETERIORATION_SCENARIO and record[name] != value:
                return False
            low, high = NORMAL_RANGES[name]
            if scenario == NORMAL_SCENARIO and not low <= record[name] <= high:
                return False
    return True


def check_rerun(report: Report, folder: Path, before: bytes, base_url: str, patient_ids: tuple[str, ...], seed: str) -> None:
    status = generate.main(["--seed", seed, "--output", str(folder.parent)])
    after = (folder / "manifest.json").read_bytes()
    report.check(
        "Rerun writes identical files", "same manifest, files and checksums", "same" if after == before else "different", status == 0 and after == before
    )
    with httpx.Client(base_url=base_url, headers={"Accept": "application/fhir+json"}, timeout=30) as client:
        totals = Counter(len(batch_encounters(client, seed, patient_id)) for patient_id in patient_ids)
    report.check("Rerun reuses the HAPI encounters", "2 batch encounters per patient", f"{dict(totals)}", totals == Counter({2: len(patient_ids)}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seed", default=os.getenv("SIMULATOR_SCENARIO_SEED") or generate.DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=generate.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    report = Report(scenario="local_cohort", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        map_file = Path(os.getenv("FHIR_RESOURCE_MAP_FILE") or DEFAULT_MAP)
        base_url = (os.getenv("FHIR_BASE_URL") or "http://127.0.0.1:8080/fhir").rstrip("/")
        if not map_file.is_file():
            raise Blocked("the local resource map is missing; load the cohort first")
        patient_ids = cohort_patient_ids(map_file)
        folder = args.output / f"seed-{args.seed}_cohort-{len(patient_ids)}"
        if not (folder / "manifest.json").is_file():
            raise Blocked("the batch is missing; run python -m jobs.batch_vitals.generate first")
        report.parameters = {"cohort_size": cohort_size(), "seed": args.seed}
        scenarios = check_hapi(report, base_url, patient_ids, args.seed)
        before = check_files(report, folder, patient_ids, scenarios)
        check_rerun(report, folder, before, base_url, patient_ids, args.seed)
    except Exception as failure:
        error = failure
    report.finish(error)
    out = report.write()
    sys.stdout.write(f"local_cohort: {report.status} ({out.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
