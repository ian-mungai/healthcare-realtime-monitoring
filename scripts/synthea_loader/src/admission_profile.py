"""Read each cohort patient's admission profile from their Synthea bundle: the hospitals they used and their disorders.

The simulator and the batch generator plan each simulated admission from this profile (facility, admitting diagnosis),
so admissions follow the patient's own Synthea history. No name or other identifying detail of the patient is kept.
"""

from __future__ import annotations

from typing import Any

SNOMED_SYSTEM = "http://snomed.info/sct"
# Synthea classes for hospital stays and emergency visits; other classes are clinic and wellness visits.
HOSPITAL_ENCOUNTER_CLASSES = {"IMP", "EMER"}


def admission_profile(bundle: dict[str, Any]) -> dict[str, Any]:
    """The patient's hospital facilities (any facility when never admitted) and disorders, in first-seen order.

    hospital_diagnoses holds the disorders diagnosed at a hospital or emergency visit; admissions prefer them.
    birth_date sets the patient's age group at each simulated admission (the planted signal's 65-and-over effect).
    """
    hospitals: dict[str, str] = {}
    facilities: dict[str, str] = {}
    diagnoses: dict[str, str] = {}
    hospital_diagnoses: dict[str, str] = {}
    hospital_visits = {
        f"urn:uuid:{entry['resource'].get('id')}"
        for entry in bundle.get("entry", [])
        if entry.get("resource", {}).get("resourceType") == "Encounter" and entry["resource"].get("class", {}).get("code") in HOSPITAL_ENCOUNTER_CLASSES
    }
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Encounter":
            provider = resource.get("serviceProvider") or {}
            organization_id = str(provider.get("reference", "")).rsplit("|", 1)[-1]
            if not organization_id or not provider.get("display"):
                continue
            facilities.setdefault(organization_id, provider["display"])
            if resource.get("class", {}).get("code") in HOSPITAL_ENCOUNTER_CLASSES:
                hospitals.setdefault(organization_id, provider["display"])
        elif resource.get("resourceType") == "Condition":
            for coding in resource.get("code", {}).get("coding", []):
                if coding.get("system") == SNOMED_SYSTEM and str(coding.get("display", "")).endswith("(disorder)"):
                    diagnoses.setdefault(coding["code"], coding["display"])
                    if resource.get("encounter", {}).get("reference") in hospital_visits:
                        hospital_diagnoses.setdefault(coding["code"], coding["display"])
    chosen = hospitals or facilities
    patient: dict[str, Any] = next((entry["resource"] for entry in bundle.get("entry", []) if entry.get("resource", {}).get("resourceType") == "Patient"), {})
    return {
        "birth_date": patient.get("birthDate"),
        "facilities": [{"id": organization_id, "name": name} for organization_id, name in chosen.items()],
        "diagnoses": [{"code": code, "display": display} for code, display in diagnoses.items()],
        "hospital_diagnoses": [{"code": code, "display": display} for code, display in hospital_diagnoses.items()],
    }
