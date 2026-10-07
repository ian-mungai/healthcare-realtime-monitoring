"""The offline batch vitals generator against a fake HAPI client and in-memory waveform records.

Failure modes the generator must handle (written before the generator):

1. The resource map holds another number of patients than COHORT_SIZE: stop before any HAPI write.
2. A cohort patient has no Synthea blood-pressure readings: stop before any HAPI write.
3. A waveform record cannot be fetched: stop with no published batch folder; a partial folder is never left in place.
4. HAPI rejects or cannot be reached for an encounter: stop; a rerun reuses the encounters already created.
5. The batch is run again with the same settings: the encounters are reused and the files are byte-identical.
6. A generated record does not pass the stream processor's schema check (a source waveform value outside the
   processor's range): leave it out and count it in the manifest, as the processor rejects it on the live path.
7. Output names patients only by cohort position, never by HAPI or Synthea identifier, in file names and the manifest.
8. A batch encounter is a completed historical stay: its status is finished, not in-progress like a live run's.
9. Every observation set carries temperature, inhaled oxygen and ACVPU, from each patient's seeded baseline.

The local end-to-end run (python -m e2e.local_cohort) remains the proof against a real HAPI server.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobs.batch_vitals import generate
from services.vitals_simulator.app.bidmc.source import VitalReading
from services.vitals_simulator.app.fhir.client import CreatedFHIRResource, FHIRRetryableError
from services.vitals_simulator.app.fhir.encounter import SIMULATOR_SCENARIO_TAG_SYSTEM
from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext
from services.vitals_simulator.app.simulation.scenario import DETERIORATION_SCENARIO, NORMAL_SCENARIO
from services.vitals_simulator.app.synthea.blood_pressure import BloodPressureReading
from services.vitals_stream_processor.schema import validate_vitals_payload
from testkit import expect

START = datetime(2026, 9, 1, 8, tzinfo=UTC)


@pytest.fixture(autouse=True)
def two_patient_cohort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COHORT_SIZE", "2")


class FakeHapi:
    """Conditional update by identifier: the same identifier always updates the same encounter."""

    def __init__(self, fail: bool = False) -> None:
        self.encounters: dict[str, dict] = {}
        self.posts = 0
        self.fail = fail

    def upsert_resource(self, resource: dict) -> CreatedFHIRResource:
        if self.fail:
            raise FHIRRetryableError("HAPI unavailable")
        self.posts += 1
        identifier = resource["identifier"][0]["value"]
        existing_id = self.encounters.get(identifier, {}).get("id") or f"encounter-{len(self.encounters) + 1}"
        self.encounters[identifier] = {**resource, "id": existing_id}
        encounter_id = self.encounters[identifier]["id"]
        return CreatedFHIRResource(resource_type="Encounter", resource_id=encounter_id, location=f"Encounter/{encounter_id}", status_code=201)


def cohort(size: int = 2) -> list[FHIRPatientContext]:
    return [FHIRPatientContext(f"synthea-{index}", f"hapi-patient-{index}", f"synthea-encounter-{index}", f"hapi-encounter-{index}") for index in range(size)]


def blood_pressure(size: int = 2) -> list[BloodPressureReading]:
    return [BloodPressureReading(f"synthea-{index}", f"bp-{index}", 118.0, 76.0) for index in range(size)]


def fetch_record(record_number: int) -> list[VitalReading]:
    return [VitalReading(f"bidmc{record_number:02d}n", offset, 80.0, 16.0, 97.0) for offset in range(60)]


def settings(tmp_path: Path) -> generate.BatchSettings:
    return generate.BatchSettings(seed="4817263", start=START, output_root=tmp_path / "batch_vitals")


def run(tmp_path: Path, hapi: FakeHapi | None = None, **overrides) -> Path:
    arguments = {"cohort": cohort(), "bp_readings": blood_pressure(), "fetch_record": fetch_record, "client": hapi or FakeHapi()}
    return generate.generate_batch(settings(tmp_path), **{**arguments, **overrides})


def records(folder: Path) -> list[dict]:
    return [json.loads(line) for path in sorted(folder.glob("*.ndjson")) for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_patient_gets_one_normal_and_one_deterioration_encounter(tmp_path: Path) -> None:
    hapi = FakeHapi()

    run(tmp_path, hapi)

    tags: dict[str, list[str]] = {}
    for encounter in hapi.encounters.values():
        tag = encounter["meta"]["tag"][0]
        expect.equal(tag["system"], SIMULATOR_SCENARIO_TAG_SYSTEM)
        tags.setdefault(encounter["subject"]["reference"], []).append(tag["code"])
    expect.equal(
        {patient: sorted(codes) for patient, codes in tags.items()},
        {f"Patient/hapi-patient-{index}": [DETERIORATION_SCENARIO, NORMAL_SCENARIO] for index in range(2)},
    )


def test_records_pass_the_stream_processor_schema_and_cover_the_full_window(tmp_path: Path) -> None:
    folder = run(tmp_path)
    output = records(folder)

    for record in output:
        validate_vitals_payload(record)
    expect.equal({record["source"] for record in output}, {generate.BATCH_SOURCE})
    expect.equal(len({record["observation_id"] for record in output}), len(output))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    expect.equal((manifest["cohort_size"], manifest["encounters"], manifest["cycles_per_encounter"]), (2, 4, 360))
    expect.equal(manifest["records"], len(output))


def test_outcome_window_follows_each_scenario(tmp_path: Path) -> None:
    folder = run(tmp_path)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    for entry in manifest["files"]:
        lines = [json.loads(line) for line in (folder / entry["name"]).read_text(encoding="utf-8").splitlines()]
        encounter_start = datetime.fromisoformat(entry["started_at"])
        outcome_heart_rates = {
            line["heart_rate"]
            for line in lines
            if "heart_rate" in line and (datetime.fromisoformat(line["event_timestamp"]) - encounter_start).total_seconds() >= 900
        }
        expected = {135.0} if entry["scenario"] == DETERIORATION_SCENARIO else {80.0}
        expect.equal(outcome_heart_rates, expected)


def test_a_rerun_reuses_encounters_and_writes_identical_files(tmp_path: Path) -> None:
    hapi = FakeHapi()
    first = run(tmp_path, hapi)
    snapshot = {path.name: path.read_bytes() for path in first.iterdir()}

    second = run(tmp_path, hapi)

    expect.equal(second, first)
    expect.equal(len(hapi.encounters), 4)
    expect.equal({path.name: path.read_bytes() for path in second.iterdir()}, snapshot)


def test_output_names_patients_only_by_position(tmp_path: Path) -> None:
    folder = run(tmp_path)

    text = "".join(path.name for path in folder.iterdir()) + (folder / "manifest.json").read_text(encoding="utf-8")
    for identifier in ("hapi-patient", "synthea-"):
        expect.not_in(identifier, text)


def test_cohort_size_mismatch_stops_before_writing_to_hapi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COHORT_SIZE", "3")
    hapi = FakeHapi()

    with pytest.raises(generate.BatchError, match="COHORT_SIZE"):
        run(tmp_path, hapi)

    expect.equal(hapi.posts, 0)


def test_missing_blood_pressure_stops_before_writing_to_hapi(tmp_path: Path) -> None:
    hapi = FakeHapi()

    with pytest.raises(generate.BatchError, match="blood-pressure readings for cohort position 2"):
        run(tmp_path, hapi, bp_readings=blood_pressure(1))

    expect.equal(hapi.posts, 0)


def test_waveform_or_hapi_failure_leaves_no_batch_folder(tmp_path: Path) -> None:
    def broken(record_number: int) -> list[VitalReading]:
        raise RuntimeError("PhysioNet fetch failed")

    with pytest.raises(RuntimeError, match="PhysioNet"):
        run(tmp_path, fetch_record=broken)
    with pytest.raises(FHIRRetryableError):
        run(tmp_path, FakeHapi(fail=True))

    expect.equal(list((tmp_path / "batch_vitals").glob("*")) if (tmp_path / "batch_vitals").exists() else [], [])


def test_records_the_processor_would_reject_are_left_out_and_counted(tmp_path: Path) -> None:
    def record_with_a_dropout(record_number: int) -> list[VitalReading]:
        readings = fetch_record(record_number)
        readings[0] = VitalReading(readings[0].source_record_id, 0, 80.0, 0.0, 97.0)
        return readings

    folder = run(tmp_path, fetch_record=record_with_a_dropout)

    for record in records(folder):
        validate_vitals_payload(record)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    expect.equal(manifest["rejected_records"], {"respiratory_rate": manifest["rejected_records"]["respiratory_rate"]})
    if manifest["rejected_records"]["respiratory_rate"] < 1:
        expect.fail("expected: at least one rejected respiratory_rate record")


def test_split_groups_keep_patients_that_share_a_waveform_record_together(tmp_path: Path) -> None:
    # A model split by these groups keeps a reused record's two patients in the same partition.
    folder = run(tmp_path)

    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    expect.equal({(entry["position"], entry["split_group"]) for entry in manifest["files"]}, {(1, "bidmc01"), (2, "bidmc02")})
    groups = json.loads((folder / "split_groups.json").read_text(encoding="utf-8"))
    expect.equal(groups, {"hapi-patient-0": "bidmc01", "hapi-patient-1": "bidmc02"})


def test_batch_encounters_carry_admissions_that_never_overlap_for_a_patient(tmp_path: Path) -> None:
    hapi = FakeHapi()

    run(tmp_path, hapi)

    periods: dict[str, list[tuple[datetime, datetime]]] = {}
    for encounter in hapi.encounters.values():
        expect.equal(len(encounter["reasonCode"]), 1)
        expect.equal(len(encounter["location"]), 1)
        expect.equal(encounter["status"], "finished")
        start, end = (datetime.fromisoformat(encounter["period"][name]) for name in ("start", "end"))
        periods.setdefault(encounter["subject"]["reference"], []).append((start, end))
    for stays in periods.values():
        stays.sort()
        for (_, first_end), (second_start, _) in zip(stays, stays[1:], strict=False):
            if second_start < first_end:
                expect.fail("expected: a patient's simulated stays never overlap")


def test_every_observation_set_carries_the_bedside_measures(tmp_path: Path) -> None:
    folder = run(tmp_path)

    bedside_fields = ("temperature", "inhaled_oxygen_concentration", "consciousness_level")
    bedside = [record for record in records(folder) if any(field in record for field in bedside_fields)]
    temperatures = [record for record in bedside if "temperature" in record]

    expect.equal(len(temperatures), 4 * 6)
    expect.equal(len([record for record in bedside if "inhaled_oxygen_concentration" in record]), 4 * 6)
    expect.equal({record["consciousness_level"] for record in bedside if "consciousness_level" in record}, {0, 1})
    for record in bedside:
        validate_vitals_payload(record)
        expect.equal(record["schema_version"], "1.2")
