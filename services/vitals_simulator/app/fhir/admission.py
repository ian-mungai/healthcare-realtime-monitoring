"""Plan a simulated hospital admission: facility, unit, admitting diagnosis, length of stay and admission hour.

The plan is seeded by the scenario seed, the patient and the run, so a rerun gives the same admission. The facility and
diagnosis come from the patient's Synthea admission profile (scripts/synthea_loader/src/admission_profile.py). Only
disorders on ADMITTING_DIAGNOSES qualify: conditions that lead to an inpatient stay with vital-sign monitoring. A patient
with none of them gets a fallback from that list, marked "simulator_fallback" instead of "synthea_history". Nothing here
depends on the outcome scenario, so admitting diagnosis works as a negative control for the subgroup analysis.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

SNOMED_SYSTEM = "http://snomed.info/sct"
SYNTHEA_SYSTEM = "https://github.com/synthetichealth/synthea"
UNITS = ("Medical intensive care unit", "Step-down unit", "Medical-surgical ward")
UNIT_WEIGHTS = (0.2, 0.3, 0.5)
MIN_LENGTH_OF_STAY_HOURS = 24
MAX_LENGTH_OF_STAY_HOURS = 144
# SNOMED CT disorders that lead to an inpatient stay with vital-sign monitoring. Outpatient conditions (gingivitis,
# sinusitis) and emergency visits usually treated and discharged (sprains, lacerations) are left out.
ADMITTING_DIAGNOSES = {
    "22298006": "Myocardial infarction (disorder)",
    "401303003": "Acute ST segment elevation myocardial infarction (disorder)",
    "401314000": "Acute non-ST segment elevation myocardial infarction (disorder)",
    "88805009": "Chronic congestive heart failure (disorder)",
    "49436004": "Atrial fibrillation (disorder)",
    "132281000119108": "Acute deep venous thrombosis (disorder)",
    "91302008": "Sepsis (disorder)",
    "770349000": "Sepsis caused by virus (disorder)",
    "76571007": "Septic shock (disorder)",
    "27942005": "Shock (disorder)",
    "233604007": "Pneumonia (disorder)",
    "840539006": "Disease caused by severe acute respiratory syndrome coronavirus 2 (disorder)",
    "389087006": "Hypoxemia (disorder)",
    "65710008": "Acute respiratory failure (disorder)",
    "195951007": "Acute exacerbation of chronic obstructive airways disease (disorder)",
    "185086009": "Chronic obstructive bronchitis (disorder)",
    "87433001": "Pulmonary emphysema (disorder)",
    "45816000": "Pyelonephritis (disorder)",
    "128045006": "Cellulitis (disorder)",
    "46177005": "End-stage renal disease (disorder)",
    "213150003": "Kidney transplant failure and rejection (disorder)",
    "74400008": "Appendicitis (disorder)",
    "47693006": "Rupture of appendix (disorder)",
    "65275009": "Acute cholecystitis (disorder)",
    "312157006": "Infectious mediastinitis (disorder)",
    "128613002": "Seizure disorder (disorder)",
    "84757009": "Epilepsy (disorder)",
    "62564004": "Concussion with loss of consciousness (disorder)",
    "1149222004": "Overdose (disorder)",
    "359817006": "Closed fracture of hip (disorder)",
    "262521009": "Traumatic injury of spinal cord and/or vertebral column (disorder)",
    "1734006": "Fracture of vertebral column with spinal cord injury (disorder)",
    "283545005": "Gunshot wound (disorder)",
    "262574004": "Bullet wound (disorder)",
    "398254007": "Pre-eclampsia (disorder)",
    "198992004": "Eclampsia in pregnancy (disorder)",
}
# Common medical admissions, used when the patient's Synthea history holds no admitting diagnosis.
FALLBACK_CODES = ("233604007", "91302008", "88805009", "195951007", "45816000", "128045006")
FALLBACK_DIAGNOSES = tuple((code, ADMITTING_DIAGNOSES[code]) for code in FALLBACK_CODES)
HISTORY_SOURCE = "synthea_history"
FALLBACK_SOURCE = "simulator_fallback"
FALLBACK_FACILITY = {"id": "synthea-fallback-facility", "name": "Regional General Hospital"}


@dataclass(frozen=True)
class Admission:
    facility_id: str
    facility_name: str
    unit: str
    diagnosis_code: str
    diagnosis_display: str
    diagnosis_source: str
    length_of_stay_hours: int
    admit_hour: int

    def discharge_at(self, started_at: datetime) -> datetime:
        return started_at + timedelta(hours=self.length_of_stay_hours)


def plan_admission(profile: dict[str, Any] | None, seed: str | int | None, patient_id: str, run_id: str) -> Admission:
    """One seeded admission for the patient and run."""
    digest = hashlib.sha256(f"admission:{seed}:{patient_id}:{run_id}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    facilities = (profile or {}).get("facilities") or [FALLBACK_FACILITY]
    # Prefer admitting diagnoses from a hospital or emergency visit, then from any visit, then a fallback.
    source = HISTORY_SOURCE
    diagnoses = admitting((profile or {}).get("hospital_diagnoses")) or admitting((profile or {}).get("diagnoses"))
    if not diagnoses:
        source, diagnoses = FALLBACK_SOURCE, list(FALLBACK_DIAGNOSES)
    facility = facilities[int(rng.integers(len(facilities)))]
    code, display = diagnoses[int(rng.integers(len(diagnoses)))]
    return Admission(
        facility_id=facility["id"],
        facility_name=facility["name"],
        unit=UNITS[int(rng.choice(len(UNITS), p=UNIT_WEIGHTS))],
        diagnosis_code=code,
        diagnosis_display=display,
        diagnosis_source=source,
        length_of_stay_hours=int(rng.integers(MIN_LENGTH_OF_STAY_HOURS, MAX_LENGTH_OF_STAY_HOURS + 1)),
        admit_hour=int(rng.integers(0, 24)),
    )


def admitting(listed: list[dict[str, str]] | None) -> list[tuple[str, str]]:
    """The listed disorders that are admitting diagnoses, in profile order."""
    return [(item["code"], item["display"]) for item in listed or [] if item["code"] in ADMITTING_DIAGNOSES]


def admission_fields(admission: Admission, started_at: datetime) -> dict[str, Any]:
    """The FHIR Encounter elements that carry the admission."""
    return {
        "reasonCode": [
            {
                "coding": [{"system": SNOMED_SYSTEM, "code": admission.diagnosis_code, "display": admission.diagnosis_display}],
                "text": admission.diagnosis_source,
            }
        ],
        "serviceProvider": {"identifier": {"system": SYNTHEA_SYSTEM, "value": admission.facility_id}, "display": admission.facility_name},
        "location": [{"location": {"display": admission.unit}}],
        "period": {"start": started_at.isoformat(), "end": admission.discharge_at(started_at).isoformat()},
    }
