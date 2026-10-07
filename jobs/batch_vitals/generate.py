"""Generate a full-length vitals batch for every cohort patient without streaming it.

Usage: python -m jobs.batch_vitals.generate [--seed SEED] [--start ISO-8601] [--output DIRECTORY]

Each patient gets two 30-minute encounters, one normal and one deterioration_proxy, so every patient has both outcome
classes. The run creates the encounters in HAPI FHIR with the simulator's scenario tags and builds every observation with
the live simulator's own scenario, waveform and blood-pressure code. It converts each observation with the FHIR
webhook's transform, so each record is the same event the stream processor receives from the live path. Records are
checked against the processor schema: records it would reject are counted, not written. The rest are written as one
NDJSON file per encounter, plus a manifest, under build/batch_vitals/seed-<SEED>_cohort-<SIZE>/. Settings come from
the environment: COHORT_SIZE, FHIR_BASE_URL and FHIR_RESOURCE_MAP_FILE. A rerun with the same settings reuses the
encounters and writes identical files. split_groups.json maps each patient to its waveform record, so a model split by
record keeps the two patients that share a record in one partition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from scripts.synthea_loader.src.cohort import cohort_size
from services.fhir_webhook.app.models import FHIRWebhookEvent
from services.fhir_webhook.app.vitals import transform_fhir_vitals
from services.vitals_simulator.app.bidmc.source import VitalReading, bidmc_source_for_position, fetch_remote_bidmc_record, rotate_readings, vary_reused_readings
from services.vitals_simulator.app.fhir.admission import Admission, plan_admission
from services.vitals_simulator.app.fhir.client import CreatedFHIRResource, HAPIFHIRClient
from services.vitals_simulator.app.fhir.encounter import build_simulator_encounter
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext, get_patient_cohort
from services.vitals_simulator.app.simulation.cycle import build_simulator_event
from services.vitals_simulator.app.simulation.scenario import LABEL_WINDOW_SECONDS, SCENARIOS, apply_vital_scenario, choose_patient_scenarios
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading, load_synthea_blood_pressure_readings
from services.vitals_simulator.app.synthea.blood_pressure_cadence import BloodPressureCadence
from services.vitals_stream_processor.schema import PermanentRecordError, validate_vitals_payload

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "build" / "batch_vitals"
DEFAULT_RECORD_CACHE = REPO_ROOT / "build" / "bidmc_cache"
DEFAULT_SEED = "4817263"
DEFAULT_START = "2026-09-01T08:00:00+00:00"
BATCH_SOURCE = "batch_simulator"
RUNS_PER_PATIENT = 2
# A patient's simulated admissions start this many days apart, longer than the longest stay, so stays never overlap.
ENCOUNTER_SPACING_DAYS = 14
# Stable namespace for observation IDs, so the same observation gets the same ID on every run.
OBSERVATION_NAMESPACE = uuid.UUID("4c7a1f9e-2b8d-5e3a-9f61-0d2c7b5a8e14")


class BatchError(RuntimeError):
    """The batch cannot run with these inputs; the message names the input, never an identifier."""


class EncounterClient(Protocol):
    def upsert_resource(self, resource: dict) -> CreatedFHIRResource: ...


@dataclass(frozen=True)
class BatchSettings:
    seed: str
    start: datetime
    output_root: Path = DEFAULT_OUTPUT_ROOT
    interval_seconds: int = 5
    window_seconds: int = LABEL_WINDOW_SECONDS
    bp_interval_seconds: int = 300

    @property
    def cycles(self) -> int:
        return self.window_seconds // self.interval_seconds


@dataclass(frozen=True)
class PlannedEncounter:
    position: int
    run: int
    scenario: str
    started_at: datetime
    context: FHIRPatientContext
    readings: list[VitalReading]
    bp_readings: list[BloodPressureReading]
    # Patients that share a waveform record share a group, so a split by group keeps them in one partition.
    split_group: str
    admission: Admission


def run_identifier(settings: BatchSettings, run: int) -> str:
    return f"batch-{settings.seed}-{run}"


def plan_scenarios(patient_ids: list[str], seed: str) -> dict[str, tuple[str, str]]:
    """The seeded first scenario for each patient, then the other one, so both runs cover both outcome classes."""
    first = choose_patient_scenarios(patient_ids, seed)
    return {patient_id: (first[patient_id], next(scenario for scenario in SCENARIOS if scenario != first[patient_id])) for patient_id in patient_ids}


def plan_encounters(
    settings: BatchSettings, cohort: list[FHIRPatientContext], bp_readings: list[BloodPressureReading], fetch_record: Callable[[int], list[VitalReading]]
) -> list[PlannedEncounter]:
    """Check every input and fetch every waveform record before anything is written to HAPI or disk."""
    expected = cohort_size()
    if len(cohort) != expected:
        raise BatchError(f"the resource map holds {len(cohort)} patients but COHORT_SIZE is {expected}")
    readings_by_patient: dict[str, list[BloodPressureReading]] = {}
    for reading in bp_readings:
        readings_by_patient.setdefault(reading.source_patient_id, []).append(reading)
    for position, context in enumerate(cohort, start=1):
        if not readings_by_patient.get(context.synthea_patient_id):
            raise BatchError(f"no blood-pressure readings for cohort position {position}; rerun scripts/export_vitals_simulator_bp.py")
    records: dict[int, list[VitalReading]] = {}
    scenarios = plan_scenarios([context.hapi_patient_id for context in cohort], settings.seed)
    planned = []
    for position, context in enumerate(cohort, start=1):
        record_number, epoch = bidmc_source_for_position(position)
        if record_number not in records:
            records[record_number] = fetch_record(record_number)
        if not records[record_number]:
            raise BatchError(f"waveform record {record_number} has no readings")
        for run, scenario in enumerate(scenarios[context.hapi_patient_id], start=1):
            admission = plan_admission(context.admission_profile, settings.seed, context.hapi_patient_id, run_identifier(settings, run))
            planned.append(
                PlannedEncounter(
                    position=position,
                    run=run,
                    scenario=scenario,
                    started_at=settings.start + timedelta(days=(run - 1) * ENCOUNTER_SPACING_DAYS, hours=admission.admit_hour),
                    context=context,
                    readings=vary_reused_readings(rotate_readings(records[record_number], epoch), record_number, epoch),
                    bp_readings=readings_by_patient[context.synthea_patient_id],
                    split_group=f"bidmc{record_number:02d}",
                    admission=admission,
                )
            )
    return planned


def encounter_records(settings: BatchSettings, encounter: PlannedEncounter, encounter_id: str, rejected: Counter[str]) -> Iterator[dict[str, Any]]:
    """Yield the processor records for one encounter, cycle by cycle, exactly as the live simulator builds them.

    A record the processor would reject, such as a waveform dropout outside its range, is left out and counted by
    the field it fails on, as the live path rejects it.
    """
    patient_id = encounter.context.hapi_patient_id
    cadence = BloodPressureCadence(readings=encounter.bp_readings, interval_seconds=settings.bp_interval_seconds)
    available = len(encounter.readings)
    for cycle in range(settings.cycles):
        source = encounter.readings[cycle % available]
        elapsed_seconds = cycle * settings.interval_seconds
        reading = replace(source, offset_seconds=source.offset_seconds + (cycle // available) * available)
        reading = apply_vital_scenario(reading, encounter.scenario, elapsed_seconds)
        cycle_timestamp = encounter.started_at + timedelta(seconds=elapsed_seconds)
        event = build_simulator_event(
            reading=reading,
            patient_id=patient_id,
            encounter_id=encounter_id,
            simulation_start=cycle_timestamp - timedelta(seconds=reading.offset_seconds),
            bp_cadence=cadence,
            bp_elapsed_seconds=elapsed_seconds,
            scenario=encounter.scenario,
        )
        for observation in event.observations:
            identifier = observation["identifier"][0]["value"]
            observation["id"] = str(uuid.uuid5(OBSERVATION_NAMESPACE, f"{encounter_id}|{identifier}"))
            received_at = datetime.fromisoformat(observation["effectiveDateTime"])
            record = transform_fhir_vitals(
                FHIRWebhookEvent(received_at=received_at, resource_type="Observation", resource_id=observation["id"], payload=observation)
            )
            record["source"] = BATCH_SOURCE
            try:
                validate_vitals_payload(record)
            except PermanentRecordError as error:
                rejected[str(error).split(" ", 1)[0]] += 1
                continue
            yield record


def generate_batch(
    settings: BatchSettings,
    cohort: list[FHIRPatientContext],
    bp_readings: list[BloodPressureReading],
    fetch_record: Callable[[int], list[VitalReading]],
    client: EncounterClient,
) -> Path:
    """Create the encounters, write the batch to a staging folder and publish it only when every record is valid."""
    planned = plan_encounters(settings, cohort, bp_readings, fetch_record)
    batch_name = f"seed-{settings.seed}_cohort-{len(cohort)}"
    final = settings.output_root / batch_name
    staging = settings.output_root / f".staging-{batch_name}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.mkdir(parents=True)
        files: list[dict[str, Any]] = []
        rejected: Counter[str] = Counter()
        for encounter in planned:
            encounter_resource = build_simulator_encounter(
                encounter.context.hapi_patient_id,
                run_identifier(settings, encounter.run),
                encounter.started_at,
                scenario=encounter.scenario,
                admission=encounter.admission,
                status="finished",
            )
            created = client.upsert_resource(encounter_resource)
            name = f"position_{encounter.position:03d}_run_{encounter.run}.ndjson"
            lines = [json.dumps(record, sort_keys=True) for record in encounter_records(settings, encounter, created.resource_id, rejected)]
            content = ("\n".join(lines) + "\n").encode("utf-8")
            (staging / name).write_bytes(content)
            files.append(
                {
                    "name": name,
                    "position": encounter.position,
                    "run": encounter.run,
                    "scenario": encounter.scenario,
                    "split_group": encounter.split_group,
                    "started_at": encounter.started_at.isoformat(),
                    "records": len(lines),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        manifest = {
            "schema_version": 1,
            "seed": settings.seed,
            "cohort_size": len(cohort),
            "interval_seconds": settings.interval_seconds,
            "window_seconds": settings.window_seconds,
            "cycles_per_encounter": settings.cycles,
            "encounters": len(files),
            "records": sum(entry["records"] for entry in files),
            "rejected_records": dict(sorted(rejected.items())),
            "scenario_counts": dict(sorted(Counter(entry["scenario"] for entry in files).items())),
            "source": BATCH_SOURCE,
            "files": files,
        }
        groups = {encounter.context.hapi_patient_id: encounter.split_group for encounter in planned}
        (staging / "split_groups.json").write_text(json.dumps(groups, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        shutil.rmtree(final, ignore_errors=True)
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def cached_fetch(cache_dir: Path) -> Callable[[int], list[VitalReading]]:
    """Fetch waveform records from PhysioNet once and keep a local JSON copy for later runs."""

    def fetch(record_number: int) -> list[VitalReading]:
        path = cache_dir / f"bidmc{record_number:02d}n.json"
        if path.is_file():
            return [VitalReading(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
        readings = fetch_remote_bidmc_record(record_number)
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([reading.to_dict() for reading in readings]), encoding="utf-8")
        return readings

    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seed", default=os.getenv("SIMULATOR_SCENARIO_SEED") or DEFAULT_SEED)
    parser.add_argument("--start", default=DEFAULT_START, help="first encounter start, ISO-8601 with a UTC offset")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--record-cache", type=Path, default=DEFAULT_RECORD_CACHE)
    args = parser.parse_args(argv)
    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        parser.error("--start needs a UTC offset, for example 2026-09-01T08:00:00+00:00")
    settings = BatchSettings(seed=str(args.seed), start=start.astimezone(UTC), output_root=args.output)
    folder = generate_batch(settings, get_patient_cohort(), load_synthea_blood_pressure_readings(), cached_fetch(args.record_cache), HAPIFHIRClient())
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    shown = folder.relative_to(REPO_ROOT) if folder.is_relative_to(REPO_ROOT) else folder
    sys.stdout.write(f"Wrote {manifest['records']} records for {manifest['encounters']} encounters to {shown}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
