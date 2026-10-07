"""Choose the attending provider of a simulated admission from the synthetic provider roster.

The roster is the dbt provider seed (dbt/seeds/provider_history.csv), built by scripts/nppes/provider_roster.py: one row
per provider version with its specialty (NUCC taxonomy code), state and validity dates. A provider attends only when the
version valid on the admission date practises in Washington and its specialty covers the unit. The choice is seeded by
the scenario seed, the patient and the run with its own stream, so it never changes the planned facility, unit,
diagnosis or length of stay. It does not depend on the outcome scenario, so specialty works as a negative control for
the subgroup analysis.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.vitals_simulator.app.fhir.admission import Admission

NPI_SYSTEM = "http://hl7.org/fhir/sid/us-npi"
PARTICIPATION_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ParticipationType"
ROSTER_STATE = "WA"
# NUCC taxonomy codes (code set 26.1) that attend each unit.
UNIT_SPECIALTIES = {
    "Medical intensive care unit": frozenset({"207RC0200X", "207RP1001X"}),
    "Step-down unit": frozenset({"207RC0000X", "207RP1001X", "208M00000X"}),
    "Medical-surgical ward": frozenset({"208M00000X", "207R00000X", "207RI0200X", "207RN0300X", "208600000X"}),
}
_CANDIDATES = (Path(__file__).resolve().parents[4] / "dbt" / "seeds" / "provider_history.csv", Path.cwd() / "dbt" / "seeds" / "provider_history.csv")


class AttendingError(RuntimeError):
    """No provider can attend; the message names the unit and date, never a provider."""


@dataclass(frozen=True)
class ProviderVersion:
    npi: str
    name: str
    taxonomy_code: str
    state: str
    valid_from: date
    valid_to: date | None

    def qualifies(self, unit: str, on: date) -> bool:
        valid = self.valid_from <= on and (self.valid_to is None or on < self.valid_to)
        return valid and self.state == ROSTER_STATE and self.taxonomy_code in UNIT_SPECIALTIES.get(unit, frozenset())


def load_roster(path: Path | None = None) -> list[ProviderVersion]:
    """Every provider version in the roster, in NPI and date order."""
    path = path or next((candidate for candidate in _CANDIDATES if candidate.is_file()), None)
    if path is None:
        raise AttendingError("dbt/seeds/provider_history.csv is not packaged with this runtime")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    versions = [
        ProviderVersion(
            npi=row["provider_npi"],
            name=row["provider_name"],
            taxonomy_code=row["taxonomy_code"],
            state=row["provider_state"],
            valid_from=date.fromisoformat(row["valid_from"]),
            valid_to=date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
        )
        for row in rows
    ]
    return sorted(versions, key=lambda version: (version.npi, version.valid_from))


def choose_attending(roster: list[ProviderVersion], unit: str, admitted_on: date, seed: str | int | None, patient_id: str, run_id: str) -> ProviderVersion:
    """One seeded attending among the versions that qualify for the unit on the admission date."""
    eligible = sorted((version for version in roster if version.qualifies(unit, admitted_on)), key=lambda version: version.npi)
    if not eligible:
        raise AttendingError(f"no roster provider attends {unit} on {admitted_on.isoformat()}")
    digest = hashlib.sha256(f"attending:{seed}:{patient_id}:{run_id}".encode()).digest()
    return eligible[int.from_bytes(digest[:8], "big") % len(eligible)]


def with_attending(
    admission: Admission, roster: list[ProviderVersion], started_at: datetime, seed: str | int | None, patient_id: str, run_id: str
) -> Admission:
    """The admission with its attending; everything already planned stays as it was."""
    attending = choose_attending(roster, admission.unit, started_at.date(), seed, patient_id, run_id)
    return replace(admission, attending_npi=attending.npi, attending_name=attending.name)


def participant_fields(admission: Admission) -> list[dict]:
    """The Encounter.participant entry naming the attending by NPI, or none before a roster was used."""
    if admission.attending_npi is None:
        return []
    return [
        {
            "type": [{"coding": [{"system": PARTICIPATION_SYSTEM, "code": "ATND", "display": "attender"}]}],
            "individual": {"identifier": {"system": NPI_SYSTEM, "value": admission.attending_npi}, "display": admission.attending_name},
        }
    ]
