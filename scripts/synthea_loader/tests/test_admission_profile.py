"""Each cohort patient's admission profile: the hospitals they used and their disorders, read from their Synthea bundle."""

from scripts.synthea_loader.src.admission_profile import admission_profile
from testkit import expect

SNOMED = "http://snomed.info/sct"
SYNTHEA = "https://github.com/synthetichealth/synthea"


def encounter(encounter_class: str, organization_id: str, name: str) -> dict:
    return {
        "resourceType": "Encounter",
        "class": {"code": encounter_class},
        "serviceProvider": {"reference": f"Organization?identifier={SYNTHEA}|{organization_id}", "display": name},
    }


def condition(code: str, display: str) -> dict:
    return {"resourceType": "Condition", "code": {"coding": [{"system": SNOMED, "code": code, "display": display}]}}


def bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "entry": [{"resource": resource} for resource in resources]}


def test_profile_lists_hospital_facilities_and_disorders_only() -> None:
    profile = admission_profile(
        bundle(
            encounter("AMB", "clinic-1", "Village Clinic"),
            encounter("IMP", "hospital-1", "General Hospital"),
            encounter("EMER", "hospital-2", "County Medical Center"),
            encounter("IMP", "hospital-1", "General Hospital"),
            condition("233604007", "Pneumonia (disorder)"),
            condition("160903007", "Full-time employment (finding)"),
            condition("233604007", "Pneumonia (disorder)"),
            condition("44054006", "Diabetes mellitus type 2 (disorder)"),
        )
    )

    expect.equal(
        profile,
        {
            "facilities": [{"id": "hospital-1", "name": "General Hospital"}, {"id": "hospital-2", "name": "County Medical Center"}],
            "diagnoses": [{"code": "233604007", "display": "Pneumonia (disorder)"}, {"code": "44054006", "display": "Diabetes mellitus type 2 (disorder)"}],
            "hospital_diagnoses": [],
            "birth_date": None,
        },
    )


def test_profile_falls_back_to_any_facility_when_the_patient_was_never_admitted() -> None:
    profile = admission_profile(bundle(encounter("AMB", "clinic-1", "Village Clinic"), encounter("WELLNESS", "clinic-2", "Family Practice")))

    expect.equal(profile["facilities"], [{"id": "clinic-1", "name": "Village Clinic"}, {"id": "clinic-2", "name": "Family Practice"}])
    expect.equal(profile["diagnoses"], [])


def test_disorders_diagnosed_at_hospital_visits_are_listed_first_as_hospital_diagnoses() -> None:
    hospital_visit = {**encounter("EMER", "hospital-1", "General Hospital"), "id": "visit-1"}
    clinic_visit = {**encounter("AMB", "clinic-1", "Village Clinic"), "id": "visit-2"}
    fracture = {**condition("46866001", "Fracture of lower limb (disorder)"), "encounter": {"reference": "urn:uuid:visit-1"}}
    sinusitis = {**condition("444814009", "Viral sinusitis (disorder)"), "encounter": {"reference": "urn:uuid:visit-2"}}

    profile = admission_profile(bundle(hospital_visit, clinic_visit, sinusitis, fracture))

    expect.equal(profile["hospital_diagnoses"], [{"code": "46866001", "display": "Fracture of lower limb (disorder)"}])


def test_profile_keeps_the_birth_date_for_the_age_group_and_nothing_identifying() -> None:
    patient = {"resourceType": "Patient", "id": "synthea-1", "birthDate": "1950-07-19", "name": [{"family": "Example"}], "address": [{"line": ["1 Main St"]}]}

    profile = admission_profile(bundle(patient))

    expect.equal(profile["birth_date"], "1950-07-19")
    expect.equal(set(profile), {"facilities", "diagnoses", "hospital_diagnoses", "birth_date"})
