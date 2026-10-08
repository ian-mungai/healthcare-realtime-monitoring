"""Check the local 100-patient cohort and its batch vitals end to end and write the report.

Usage: python -m e2e.local_cohort [--seed SEED] [--output DIRECTORY] [--signal study|null_control]

Run it after the local stack is started, the cohort is loaded into local HAPI FHIR and the batch is generated. It
reads COHORT_SIZE, FHIR_BASE_URL and FHIR_RESOURCE_MAP_FILE like the generator. The run checks
that every cohort patient exists in HAPI with three normal and three deterioration batch encounters, that the manifest
and files agree, that every record passes the stream processor's schema and follows its scenario in the outcome window
(deterioration values inside the approved ranges, varying within and between encounters), that planted_truth.json
follows the selected signal and the feature-window heart rate shows only the planted rise, and that a second
generation run reuses the encounters and writes identical files. Every run writes report.json and
report.md under artifacts/e2e/local_cohort/, passed, failed or blocked.
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
from services.vitals_simulator.app.simulation.precursor import SIGNAL_MODES
from services.vitals_simulator.app.simulation.scenario import (
    DETERIORATION_RANGES,
    DETERIORATION_SCENARIO,
    FEATURE_WINDOW_SECONDS,
    NORMAL_RANGES,
    NORMAL_SCENARIO,
)
from services.vitals_stream_processor.schema import validate_vitals_payload

DEFAULT_MAP = ROOT / "build" / "local" / "fhir_resource_map.json"
PURPOSE = (
    "Every local cohort patient has three normal and three deterioration batch encounters whose records the stream processor "
    "accepts, with the planted signal recorded and visible."
)
LIMITS = (
    "Checks the local HAPI server and the batch files only; it does not stream the batch, run dbt or train a model. Patients past "
    "the 53 waveform records reuse a record from its midpoint with seeded variation, so the 100 patients are not fully independent."
)
REPRODUCE = "Start the stack, load the cohort, generate the batch, then `.venv/bin/python -m e2e.local_cohort`."
# Positions past the 53 BIDMC records reuse record position - 53 (services/vitals_simulator/app/bidmc/source.py).
REUSED_FROM = 53
# The smallest seeded offset per vital (REUSE_VARIATION in services/vitals_simulator/app/bidmc/source.py).
MIN_REUSED_DIFFERENCE = {"heart_rate": 2.0, "respiratory_rate": 1.0, "spo2": 0.5}
PER_SCENARIO = generate.RUNS_PER_PATIENT // 2
RAMP_START_SECONDS = 300


def batch_encounters(client: httpx.Client, settings: generate.BatchSettings, patient_id: str) -> list[dict]:
    """The batch encounters HAPI holds for one patient, one search per run identifier."""
    found = []
    for run in range(1, generate.RUNS_PER_PATIENT + 1):
        value = f"{generate.run_identifier(settings, run)}:{patient_id}"
        bundle = client.get("/Encounter", params={"identifier": f"{SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM}|{value}"}).raise_for_status().json()
        found += [entry["resource"] for entry in bundle.get("entry", [])]
    return found


def check_hapi(report: Report, base_url: str, patient_ids: tuple[str, ...], settings: generate.BatchSettings) -> dict[str, str]:
    """Check patients and batch encounters in HAPI; return each batch encounter ID with its scenario."""
    missing_patients, wrong_encounters = 0, 0
    scenarios: dict[str, str] = {}
    with httpx.Client(base_url=base_url, headers={"Accept": "application/fhir+json"}, timeout=30) as client:
        for patient_id in patient_ids:
            if client.get(f"/Patient/{patient_id}").status_code != 200:
                missing_patients += 1
            encounters = batch_encounters(client, settings, patient_id)
            tags = sorted(
                tag["code"]
                for encounter in encounters
                for tag in encounter.get("meta", {}).get("tag", [])
                if tag.get("system") == SIMULATOR_SCENARIO_TAG_SYSTEM
            )
            if tags != [DETERIORATION_SCENARIO] * PER_SCENARIO + [NORMAL_SCENARIO] * PER_SCENARIO:
                wrong_encounters += 1
            for encounter in encounters:
                scenarios[encounter["id"]] = next(tag["code"] for tag in encounter["meta"]["tag"] if tag["system"] == SIMULATOR_SCENARIO_TAG_SYSTEM)
    report.check("Cohort patients in HAPI", f"all {len(patient_ids)} present", f"{missing_patients} missing", missing_patients == 0)
    report.check(
        "Three normal and three deterioration batch encounters per patient", "every patient", f"{wrong_encounters} patients differ", wrong_encounters == 0
    )
    return scenarios


def check_files(report: Report, folder: Path, patient_ids: tuple[str, ...], scenarios: dict[str, str]) -> bytes:
    manifest_bytes = (folder / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    expected = {"cohort_size": len(patient_ids), "encounters": generate.RUNS_PER_PATIENT * len(patient_ids)}
    observed = {name: manifest.get(name) for name in expected}
    report.check("Manifest size", f"{expected}", f"{observed}", observed == expected)
    counts = manifest.get("scenario_counts", {})
    report.check(
        "Scenario balance",
        f"{PER_SCENARIO * len(patient_ids)} of each",
        f"{counts}",
        counts == {DETERIORATION_SCENARIO: PER_SCENARIO * len(patient_ids), NORMAL_SCENARIO: PER_SCENARIO * len(patient_ids)},
    )
    bad_hashes = invalid = off_scenario = wrong_encounter = 0
    # Each deterioration encounter's outcome-window heart rates, to show the values vary within and between encounters.
    deterioration_heart_rates: dict[str, set[float]] = {}
    # Each normal encounter's outcome-window heart rates: a source above or below the range must not sit on its limit.
    normal_heart_rates: dict[str, set[float]] = {}
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
                if entry["scenario"] == DETERIORATION_SCENARIO and "heart_rate" in record:
                    deterioration_heart_rates.setdefault(entry["name"], set()).add(record["heart_rate"])
                if entry["scenario"] == NORMAL_SCENARIO and "heart_rate" in record:
                    normal_heart_rates.setdefault(entry["name"], set()).add(record["heart_rate"])
    report.check("File checksums", "all match the manifest", f"{bad_hashes} differ", bad_hashes == 0)
    report.check("Records accepted by the stream processor schema", f"all {records}", f"{invalid} rejected", invalid == 0 and records == manifest["records"])
    report.check("Observation IDs unique", f"{records} unique", f"{len(observation_ids)} unique", len(observation_ids) == records)
    report.check("Records belong to the HAPI encounter of their scenario", "all", f"{wrong_encounter} differ", wrong_encounter == 0)
    report.check("Outcome window follows the scenario", "all outcome-window records", f"{off_scenario} differ", off_scenario == 0)
    steady = sum(len(values) < 2 for values in deterioration_heart_rates.values())
    means = {round(sum(values) / len(values)) for values in deterioration_heart_rates.values()}
    report.check(
        "Deterioration values vary",
        "every encounter's heart rate varies and encounters differ",
        f"{steady} of {len(deterioration_heart_rates)} steady; {len(means)} distinct mean heart rates",
        steady == 0 and len(means) > 1,
    )
    flat = sum(len(values) < 2 for values in normal_heart_rates.values())
    report.check(
        "Normal values vary", "no normal encounter's outcome-window heart rate stays on one value", f"{flat} of {len(normal_heart_rates)} steady", flat == 0
    )
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
    """A deterioration record lies inside every approved deterioration range; a normal one inside the normal ranges."""
    ranges = DETERIORATION_RANGES if scenario == DETERIORATION_SCENARIO else NORMAL_RANGES
    return all(low <= record[name] <= high for name, (low, high) in ranges.items() if name in record)


def check_reuse(report: Report, folder: Path, patient_ids: tuple[str, ...]) -> None:
    """Patients that share a waveform record share a split group, and their feature-window vitals still differ."""
    groups = json.loads((folder / "split_groups.json").read_text(encoding="utf-8"))
    members = Counter(groups.values())
    report.check(
        "Split groups cover the cohort",
        f"{len(patient_ids)} patients, at most 2 per group",
        f"{len(groups)} patients in {len(members)} groups, largest {max(members.values(), default=0)}",
        set(groups) == set(patient_ids) and max(members.values(), default=0) <= 2,
    )
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    feature_means: dict[int, dict[str, float | None]] = {}
    for entry in manifest["files"]:
        if entry["run"] != 1:
            continue
        started = datetime.fromisoformat(entry["started_at"])
        values: dict[str, list[float]] = {name: [] for name in MIN_REUSED_DIFFERENCE}
        for record in map(json.loads, (folder / entry["name"]).read_text(encoding="utf-8").splitlines()):
            if (datetime.fromisoformat(record["event_timestamp"]) - started).total_seconds() < FEATURE_WINDOW_SECONDS:
                for name in values:
                    if name in record:
                        values[name].append(record[name])
        feature_means[entry["position"]] = {name: sum(found) / len(found) if found else None for name, found in values.items()}
    reused = [(position - REUSED_FROM, position) for position in feature_means if position > REUSED_FROM]
    close = [pair for pair in reused if not differs(feature_means[pair[0]], feature_means[pair[1]])]
    report.check(
        "Reused records give distinct feature-window vitals",
        f"for all {len(reused)} reused pairs, a vital mean differs by at least its minimum offset",
        f"{len(close)} pairs closer",
        not close,
    )
    missing = sorted(position for position, means in feature_means.items() if None in means.values())
    report.evidence["feature_window_vital_missing_positions"] = missing
    run_sequences: dict[int, set[tuple[float, ...]]] = {}
    for entry in manifest["files"]:
        started = datetime.fromisoformat(entry["started_at"])
        rates = [
            record["heart_rate"]
            for record in map(json.loads, (folder / entry["name"]).read_text(encoding="utf-8").splitlines())
            if "heart_rate" in record and (datetime.fromisoformat(record["event_timestamp"]) - started).total_seconds() < RAMP_START_SECONDS
        ]
        if rates:
            run_sequences.setdefault(entry["position"], set()).add(tuple(rates))
    # Two runs are copies when their pre-ramp heart-rate readings are identical; equal means alone can be chance.
    copies = sorted(position for position, sequences in run_sequences.items() if len(sequences) < generate.RUNS_PER_PATIENT)
    report.check(
        "A patient's runs do not copy each other",
        f"{generate.RUNS_PER_PATIENT} different pre-ramp heart-rate sequences per patient",
        f"{len(copies)} patients with repeated runs",
        not copies,
    )


def differs(first: dict[str, float | None], second: dict[str, float | None]) -> bool:
    """Whether any vital's feature-window mean differs by at least the minimum reuse offset for that vital."""
    for name, minimum in MIN_REUSED_DIFFERENCE.items():
        left, right = first[name], second[name]
        if left is not None and right is not None and abs(left - right) >= minimum:
            return True
    return False


def check_rerun(report: Report, folder: Path, before: bytes, base_url: str, patient_ids: tuple[str, ...], settings: generate.BatchSettings) -> None:
    status = generate.main(["--seed", settings.seed, "--output", str(folder.parent), "--signal", settings.signal])
    after = (folder / "manifest.json").read_bytes()
    report.check(
        "Rerun writes identical files", "same manifest, files and checksums", "same" if after == before else "different", status == 0 and after == before
    )
    with httpx.Client(base_url=base_url, headers={"Accept": "application/fhir+json"}, timeout=30) as client:
        totals = Counter(len(batch_encounters(client, settings, patient_id)) for patient_id in patient_ids)
    runs = generate.RUNS_PER_PATIENT
    report.check("Rerun reuses the HAPI encounters", f"{runs} batch encounters per patient", f"{dict(totals)}", totals == Counter({runs: len(patient_ids)}))


def check_planted_signal(report: Report, folder: Path, settings: generate.BatchSettings) -> None:
    """The truth file matches the plan, and the planted heart-rate rise shows in the feature-window records."""
    truth = json.loads((folder / "planted_truth.json").read_text(encoding="utf-8"))
    entries = truth["encounters"]
    deterioration = [entry for entry in entries if entry["scenario"] == DETERIORATION_SCENARIO]
    planted = [entry for entry in deterioration if entry["has_precursor"]]
    share = len(planted) / max(len(deterioration), 1)
    expected_share = truth["parameters"]["precursor_probability"]
    report.check(
        "Planted precursors follow the signal",
        f"{settings.signal}: none in normal encounters, about {expected_share:.0%} of deterioration encounters",
        f"{sum(entry['has_precursor'] for entry in entries if entry['scenario'] == NORMAL_SCENARIO)} normal, {share:.0%} of deterioration",
        not any(entry["has_precursor"] for entry in entries if entry["scenario"] == NORMAL_SCENARIO) and abs(share - expected_share) <= 0.1,
    )
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    names = {(item["position"], item["run"]): item for item in manifest["files"]}
    rises: dict[str, list[float]] = {"planted": [], "unplanted": []}
    for entry in entries:
        rise = heart_rate_rise(folder, names[(entry["position"], entry["run"])])
        if rise is not None:
            rises["planted" if entry["has_precursor"] else "unplanted"].append(rise - entry["heart_rate"])
    residual = {group: sum(values) / len(values) if values else 0.0 for group, values in rises.items()}
    report.check(
        "Feature-window heart rate shows only the planted rise",
        "the mean rise minus the planted rise is within 2 bpm of 0 in both groups",
        ", ".join(f"{group} {value:+.2f} bpm" for group, value in residual.items()),
        all(abs(value) <= 2.0 for value in residual.values()),
    )
    unseen = [entry for entry in entries if not planted_bedside_observed(folder, names[(entry["position"], entry["run"])], entry)]
    report.check(
        "Planted oxygen and confusion show in the feature window",
        "every planted start is followed by an observation set before the outcome window",
        f"{len(unseen)} of {sum(1 for entry in entries if entry['oxygen_from_seconds'] is not None or entry['confusion_from_seconds'] is not None)} unseen",
        not unseen,
    )
    report.evidence["planted_signal"] = {
        "signal": settings.signal,
        "version": truth["version"],
        "planted_share": round(share, 3),
        "residual_rise_bpm": residual,
    }


def planted_bedside_observed(folder: Path, item: dict, entry: dict) -> bool:
    """Whether a planted oxygen or confusion start appears in a feature-window observation set."""
    if entry["oxygen_from_seconds"] is None and entry["confusion_from_seconds"] is None:
        return True
    started = datetime.fromisoformat(item["started_at"])
    oxygen = confusion = False
    for record in map(json.loads, (folder / item["name"]).read_text(encoding="utf-8").splitlines()):
        if (datetime.fromisoformat(record["event_timestamp"]) - started).total_seconds() >= FEATURE_WINDOW_SECONDS:
            continue
        oxygen = oxygen or record.get("inhaled_oxygen_concentration", 21.0) > 21.0
        confusion = confusion or record.get("consciousness_level", 0) > 0
    return (entry["oxygen_from_seconds"] is None or oxygen) and (entry["confusion_from_seconds"] is None or confusion)


def heart_rate_rise(folder: Path, entry: dict) -> float | None:
    """Mean heart rate in the last 30 seconds of the feature window minus the mean before the ramp starts."""
    started = datetime.fromisoformat(entry["started_at"])
    early: list[float] = []
    late: list[float] = []
    for record in map(json.loads, (folder / entry["name"]).read_text(encoding="utf-8").splitlines()):
        if "heart_rate" not in record:
            continue
        elapsed = (datetime.fromisoformat(record["event_timestamp"]) - started).total_seconds()
        if elapsed < RAMP_START_SECONDS:
            early.append(record["heart_rate"])
        elif FEATURE_WINDOW_SECONDS - 30 <= elapsed < FEATURE_WINDOW_SECONDS:
            late.append(record["heart_rate"])
    return sum(late) / len(late) - sum(early) / len(early) if early and late else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seed", default=os.getenv("SIMULATOR_SCENARIO_SEED") or generate.DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=generate.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--signal", choices=SIGNAL_MODES, default="study")
    args = parser.parse_args(argv)
    settings = generate.BatchSettings(seed=str(args.seed), start=datetime.fromisoformat(generate.DEFAULT_START), output_root=args.output, signal=args.signal)
    report = Report(scenario="local_cohort", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        map_file = Path(os.getenv("FHIR_RESOURCE_MAP_FILE") or DEFAULT_MAP)
        base_url = (os.getenv("FHIR_BASE_URL") or "http://127.0.0.1:8080/fhir").rstrip("/")
        if not map_file.is_file():
            raise Blocked("the local resource map is missing; load the cohort first")
        patient_ids = cohort_patient_ids(map_file)
        folder = args.output / generate.batch_name(settings, len(patient_ids))
        if not (folder / "manifest.json").is_file():
            raise Blocked("the batch is missing; run python -m jobs.batch_vitals.generate first")
        report.parameters = {"cohort_size": cohort_size(), "seed": args.seed, "signal": args.signal}
        scenarios = check_hapi(report, base_url, patient_ids, settings)
        before = check_files(report, folder, patient_ids, scenarios)
        check_reuse(report, folder, patient_ids)
        check_planted_signal(report, folder, settings)
        check_rerun(report, folder, before, base_url, patient_ids, settings)
    except Exception as failure:
        error = failure
    report.finish(error)
    out = report.write()
    sys.stdout.write(f"local_cohort: {report.status} ({out.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
