"""The attending provider of a simulated admission, chosen from the synthetic provider roster.

Failure modes of the choice (written before the code):

1. A rerun picks a different attending for the same admission: the seed, patient and run must fix the choice.
2. A provider whose roster version is not valid on the admission date (not yet joined, already changed, moved out of
   state) attends: only versions valid on that date and practising in Washington qualify.
3. A provider attends a unit their specialty does not cover (a surgeon in the intensive care unit): each unit has its
   own specialties.
4. No provider qualifies for a unit on a date: stop and name the unit and date, never fall back to anyone.
5. Choosing the attending changes the facility, unit, diagnosis or length of stay: the admission stays as planned,
   so the calibrated signal and the study's admissions do not move.
6. The committed roster leaves a unit without a qualifying provider on some study date: every unit must have one on
   every date from the batch start to today.
7. The encounter does not carry the attending: it names the provider by NPI as the attending participant.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from services.vitals_simulator.app.fhir.admission import UNITS, plan_admission
from services.vitals_simulator.app.fhir.attending import (
    NPI_SYSTEM,
    UNIT_SPECIALTIES,
    AttendingError,
    ProviderVersion,
    choose_attending,
    load_roster,
    with_attending,
)
from services.vitals_simulator.app.fhir.encounter import build_simulator_encounter
from testkit import expect

ICU = "Medical intensive care unit"
WARD = "Medical-surgical ward"
CRITICAL_CARE = "207RC0200X"
SURGERY = "208600000X"
PROFILE = {"facilities": [{"id": "hospital-1", "name": "General Hospital"}], "diagnoses": [{"code": "233604007", "display": "Pneumonia (disorder)"}]}


def version(npi: str, taxonomy: str, valid_from: str, valid_to: str | None = None, state: str = "WA") -> ProviderVersion:
    return ProviderVersion(
        npi=npi,
        name=f"Provider {npi[-2:]}",
        taxonomy_code=taxonomy,
        state=state,
        valid_from=date.fromisoformat(valid_from),
        valid_to=date.fromisoformat(valid_to) if valid_to else None,
    )


ROSTER = [
    version("1000000101", CRITICAL_CARE, "2020-01-01"),
    version("1000000102", CRITICAL_CARE, "2020-01-01", "2026-07-01"),
    version("1000000103", CRITICAL_CARE, "2026-07-01"),
    version("1000000104", CRITICAL_CARE, "2020-01-01", "2026-07-01", state="OR"),
    version("1000000104", CRITICAL_CARE, "2026-07-01"),
    version("1000000105", SURGERY, "2020-01-01"),
]


def test_the_same_seed_patient_and_run_give_the_same_attending() -> None:
    first = choose_attending(ROSTER, ICU, date(2026, 8, 1), "4817263", "patient-1", "run-1")

    expect.equal(choose_attending(ROSTER, ICU, date(2026, 8, 1), "4817263", "patient-1", "run-1"), first)
    picks = {choose_attending(ROSTER, ICU, date(2026, 8, 1), "4817263", f"patient-{number}", "run-1").npi for number in range(40)}
    expect.equal(picks, {"1000000101", "1000000103", "1000000104"})


def test_only_versions_valid_in_washington_on_the_admission_date_attend() -> None:
    picks = {choose_attending(ROSTER, ICU, date(2026, 6, 15), "4817263", f"patient-{number}", "run-1") for number in range(40)}

    expect.equal({(pick.npi, pick.valid_from) for pick in picks}, {("1000000101", date(2020, 1, 1)), ("1000000102", date(2020, 1, 1))})


def test_specialty_must_cover_the_unit() -> None:
    picks = {choose_attending(ROSTER, WARD, date(2026, 8, 1), "4817263", f"patient-{number}", "run-1").npi for number in range(40)}

    expect.equal(picks, {"1000000105"})


def test_no_qualifying_provider_stops_with_the_unit_and_date() -> None:
    with pytest.raises(AttendingError, match=r"Medical-surgical ward on 2019-12-31"):
        choose_attending(ROSTER, WARD, date(2019, 12, 31), "4817263", "patient-1", "run-1")


def test_the_attending_leaves_the_planned_admission_unchanged() -> None:
    admission = plan_admission(PROFILE, "4817263", "patient-1", "run-1")
    started_at = datetime(2026, 8, 1, 8, tzinfo=UTC)

    attended = with_attending(admission, load_roster(), started_at, "4817263", "patient-1", "run-1")

    expect.equal(replace(attended, attending_npi=None, attending_name=None), admission)
    expect.not_equal(attended.attending_npi, None)


def test_the_committed_roster_covers_every_unit_on_every_study_date() -> None:
    roster = load_roster()
    day = date(2026, 6, 1)
    gaps = []
    while day <= datetime.now(UTC).date():
        gaps += [f"{unit} on {day}" for unit in UNITS if not any(provider.qualifies(unit, day) for provider in roster)]
        day += timedelta(days=1)

    expect.equal(gaps, [])
    expect.equal(set(UNIT_SPECIALTIES), set(UNITS))


def test_the_encounter_names_the_attending_by_npi() -> None:
    admission = plan_admission(PROFILE, "4817263", "patient-1", "run-1")
    started_at = datetime(2026, 8, 1, 8, tzinfo=UTC)
    attended = with_attending(admission, load_roster(), started_at, "4817263", "patient-1", "run-1")

    encounter = build_simulator_encounter("patient-1", "run-1", started_at, admission=attended)

    participant = encounter["participant"][0]
    expect.equal(participant["type"][0]["coding"][0]["code"], "ATND")
    expect.equal(participant["individual"]["identifier"], {"system": NPI_SYSTEM, "value": attended.attending_npi})
    expect.equal(participant["individual"]["display"], attended.attending_name)
