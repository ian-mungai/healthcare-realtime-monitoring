"""A simulated admission: facility, unit, admitting diagnosis, length of stay and admission hour, seeded per run.

Failure modes of the admitting diagnosis (written before the allowlist):

1. A patient's disorders are all outpatient conditions (gingivitis, sinusitis): an admission-worthy fallback is used and
   marked as the simulator's choice, not the patient's history.
2. A disorder from an emergency visit that does not need an inpatient stay (a sprain, a laceration): never chosen.
3. An admission-worthy disorder from a clinic visit (chronic heart failure): chosen and marked as the patient's history.
4. Admission-worthy disorders from a hospital or emergency visit come before those from other visits.
5. The encounter records where the diagnosis came from, so the warehouse can tell history from fallback.
"""

from datetime import UTC, datetime

from services.vitals_simulator.app.fhir.admission import ADMITTING_DIAGNOSES, FALLBACK_DIAGNOSES, UNITS, plan_admission
from services.vitals_simulator.app.fhir.encounter import build_simulator_encounter
from testkit import expect

PROFILE = {
    "facilities": [{"id": "hospital-1", "name": "General Hospital"}, {"id": "hospital-2", "name": "County Medical Center"}],
    "diagnoses": [{"code": "233604007", "display": "Pneumonia (disorder)"}, {"code": "44054006", "display": "Diabetes mellitus type 2 (disorder)"}],
}


def test_the_same_seed_patient_and_run_give_the_same_admission() -> None:
    first = plan_admission(PROFILE, "4817263", "patient-1", "batch-4817263-1")

    expect.equal(plan_admission(PROFILE, "4817263", "patient-1", "batch-4817263-1"), first)
    expect.is_in(first.facility_id, {"hospital-1", "hospital-2"})
    expect.is_in(first.unit, UNITS)
    expect.equal((first.diagnosis_code, first.diagnosis_source), ("233604007", "synthea_history"))
    if not 24 <= first.length_of_stay_hours <= 144 or not 0 <= first.admit_hour <= 23:
        expect.fail(f"expected: a stay of 24 to 144 hours and an hour of day, got {first}")


def test_runs_and_patients_vary() -> None:
    admissions = {plan_admission(PROFILE, "4817263", f"patient-{patient}", f"run-{run}") for patient in range(20) for run in range(6)}

    if len({admission.unit for admission in admissions}) < len(UNITS) or len({admission.admit_hour for admission in admissions}) < 10:
        expect.fail("expected: units and admission hours vary across patients and runs")


def test_a_patient_without_disorders_gets_a_fallback_diagnosis() -> None:
    admission = plan_admission({"facilities": PROFILE["facilities"], "diagnoses": []}, "4817263", "patient-1", "run-1")

    expect.is_in((admission.diagnosis_code, admission.diagnosis_display), FALLBACK_DIAGNOSES)
    expect.equal(admission.diagnosis_source, "simulator_fallback")


def test_outpatient_and_minor_emergency_disorders_are_never_admitting_diagnoses() -> None:
    profile = {
        "facilities": PROFILE["facilities"],
        "diagnoses": [{"code": "66383009", "display": "Gingivitis (disorder)"}, {"code": "444814009", "display": "Viral sinusitis (disorder)"}],
        "hospital_diagnoses": [
            {"code": "44465007", "display": "Sprain of ankle (disorder)"},
            {"code": "312608009", "display": "Laceration - injury (disorder)"},
        ],
    }

    admissions = [plan_admission(profile, "4817263", "patient-1", f"run-{run}") for run in range(6)]

    expect.equal({admission.diagnosis_source for admission in admissions}, {"simulator_fallback"})
    expect.equal({(admission.diagnosis_code, admission.diagnosis_display) for admission in admissions} - set(FALLBACK_DIAGNOSES), set())


def test_an_admission_worthy_disorder_from_a_clinic_visit_is_used() -> None:
    profile = {
        "facilities": PROFILE["facilities"],
        "diagnoses": [{"code": "66383009", "display": "Gingivitis (disorder)"}, {"code": "88805009", "display": "Chronic congestive heart failure (disorder)"}],
        "hospital_diagnoses": [{"code": "44465007", "display": "Sprain of ankle (disorder)"}],
    }

    admission = plan_admission(profile, "4817263", "patient-1", "run-1")

    expect.equal((admission.diagnosis_code, admission.diagnosis_source), ("88805009", "synthea_history"))


def test_every_fallback_is_on_the_admitting_list() -> None:
    expect.equal({code for code, _ in FALLBACK_DIAGNOSES} - set(ADMITTING_DIAGNOSES), set())


def test_the_encounter_carries_the_admission() -> None:
    admission = plan_admission(PROFILE, "4817263", "patient-1", "run-1")
    started_at = datetime(2026, 9, 1, 8, tzinfo=UTC)

    encounter = build_simulator_encounter("patient-1", "run-1", started_at, admission=admission)

    expect.equal(encounter["reasonCode"][0]["coding"][0]["code"], admission.diagnosis_code)
    expect.equal(encounter["reasonCode"][0]["text"], admission.diagnosis_source)
    expect.equal(encounter["serviceProvider"]["display"], admission.facility_name)
    expect.equal(encounter["location"][0]["location"]["display"], admission.unit)
    expect.equal(datetime.fromisoformat(encounter["period"]["end"]), admission.discharge_at(started_at))


def test_a_diagnosis_from_a_hospital_visit_is_preferred() -> None:
    profile = {**PROFILE, "hospital_diagnoses": [{"code": "359817006", "display": "Closed fracture of hip (disorder)"}]}

    admissions = {plan_admission(profile, "4817263", "patient-1", f"run-{run}").diagnosis_code for run in range(6)}

    expect.equal(admissions, {"359817006"})
