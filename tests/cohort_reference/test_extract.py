"""Reference rows for the warehouse: cohort demographics and payer history from Synthea, facilities, and admissions from HAPI.

Failure modes the extract must handle (written before the extract):

1. A cohort patient has no Synthea bundle: stop naming the cohort position, before writing anything.
2. A patient never changes payer: one open payer period, not zero.
3. A payer repeats after a different one: three periods, not two (only consecutive repeats merge).
4. HAPI pages its Encounter search: every page is read.
5. An encounter has no admission fields (created before admissions existed): it is skipped and counted.
6. Rows never carry a patient's name, address line or other identifying detail.
7. HAPI still holds encounters of patients from an earlier cohort: they are skipped and counted, not extracted.
8. HAPI holds the study's and the null control's encounters for the same patients: each warehouse keeps its own
   signal's encounters and skips and counts the other's.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from jobs.cohort_reference import extract
from testkit import expect

HAPI = "http://hapi.example.invalid/fhir"
SYSTEM = "https://example.org/fhir/identifier/vitals-simulator-encounter"


def patient_bundle(patient_id: str, payers: list[tuple[str, str]]) -> dict:
    patient = {
        "resourceType": "Patient",
        "id": patient_id,
        "name": [{"family": "Sample", "given": ["Person"]}],
        "birthDate": "1950-04-02",
        "gender": "female",
        "maritalStatus": {"text": "Married"},
        "address": [{"line": ["1 Example Road"], "city": "Olympia", "state": "WA"}],
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race", "extension": [{"url": "text", "valueString": "White"}]},
            {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                "extension": [{"url": "text", "valueString": "Not Hispanic or Latino"}],
            },
        ],
    }
    claims = [{"resourceType": "ExplanationOfBenefit", "insurer": {"display": payer}, "billablePeriod": {"start": start}} for start, payer in payers]
    return {"resourceType": "Bundle", "entry": [{"resource": resource} for resource in (patient, *claims)]}


def test_demographics_keep_no_identifying_detail() -> None:
    rows = extract.patient_rows({"synthea-1": "hapi-1"}, {"synthea-1": patient_bundle("synthea-1", [])})

    expect.equal(
        rows,
        [
            {
                "patient_id": "hapi-1",
                "birth_date": "1950-04-02",
                "gender": "female",
                "race": "White",
                "ethnicity": "Not Hispanic or Latino",
                "marital_status": "Married",
                "state": "WA",
            }
        ],
    )


def test_payer_history_merges_only_consecutive_repeats() -> None:
    bundle = patient_bundle(
        "synthea-1",
        [("2010-01-01T00:00:00Z", "Medicaid"), ("2011-01-01T00:00:00Z", "Medicaid"), ("2014-06-01T00:00:00Z", "Aetna"), ("2020-01-01T00:00:00Z", "Medicaid")],
    )

    rows = extract.payer_history_rows({"synthea-1": "hapi-1"}, {"synthea-1": bundle})

    expect.equal(
        [(row["payer_name"], row["valid_from"], row["valid_to"]) for row in rows],
        [("Medicaid", "2010-01-01", "2014-06-01"), ("Aetna", "2014-06-01", "2020-01-01"), ("Medicaid", "2020-01-01", None)],
    )


def test_a_patient_without_claims_gets_one_open_no_insurance_period() -> None:
    rows = extract.payer_history_rows({"synthea-1": "hapi-1"}, {"synthea-1": patient_bundle("synthea-1", [])})

    expect.equal([(row["payer_name"], row["valid_to"]) for row in rows], [(extract.NO_INSURANCE, None)])


def test_a_missing_bundle_stops_the_extract() -> None:
    with pytest.raises(extract.ExtractError, match="cohort position 1"):
        extract.patient_rows({"synthea-1": "hapi-1"}, {})


def encounter(number: int, admitted: bool = True) -> dict:
    resource: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": f"encounter-{number}",
        "identifier": [{"system": SYSTEM, "value": f"batch-1-{number}:hapi-1"}],
        "subject": {"reference": "Patient/hapi-1"},
        "period": {"start": "2026-09-01T08:00:00+00:00"},
        "meta": {"tag": [{"system": "https://example.org/fhir/CodeSystem/vitals-simulator-scenario", "code": "normal"}]},
    }
    if admitted:
        resource["period"]["end"] = "2026-09-03T08:00:00+00:00"
        resource["reasonCode"] = [
            {"coding": [{"system": "http://snomed.info/sct", "code": "233604007", "display": "Pneumonia (disorder)"}], "text": "synthea_history"}
        ]
        resource["serviceProvider"] = {"identifier": {"value": "hospital-1"}, "display": "General Hospital"}
        resource["location"] = [{"location": {"display": "Step-down unit"}}]
    return resource


@respx.mock
def test_admissions_read_every_page_and_skip_encounters_without_admission_fields() -> None:
    first = {
        "resourceType": "Bundle",
        "entry": [{"resource": encounter(1)}, {"resource": encounter(2, admitted=False)}],
        "link": [{"relation": "next", "url": f"{HAPI}/page-2"}],
    }
    second = {"resourceType": "Bundle", "entry": [{"resource": encounter(3)}], "link": []}
    respx.get(f"{HAPI}/Encounter").mock(return_value=httpx.Response(200, json=first))
    respx.get(f"{HAPI}/page-2").mock(return_value=httpx.Response(200, json=second))

    rows, skipped = extract.admission_rows(HAPI, {"hapi-1"})

    expect.equal([row["encounter_id"] for row in rows], ["encounter-1", "encounter-3"])
    expect.equal(skipped, {"without_admission": 1, "outside_cohort": 0, "other_signal": 0})
    expect.equal(
        {key: rows[0][key] for key in ("patient_id", "facility_id", "unit", "diagnosis_code", "diagnosis_source", "scenario", "admitted_at", "discharged_at")},
        {
            "patient_id": "hapi-1",
            "facility_id": "hospital-1",
            "unit": "Step-down unit",
            "diagnosis_code": "233604007",
            "diagnosis_source": "synthea_history",
            "scenario": "normal",
            "admitted_at": "2026-09-01T08:00:00+00:00",
            "discharged_at": "2026-09-03T08:00:00+00:00",
        },
    )


@respx.mock
def test_admissions_skip_patients_outside_the_cohort() -> None:
    former = encounter(4)
    former["subject"] = {"reference": "Patient/former-patient"}
    page = {"resourceType": "Bundle", "entry": [{"resource": encounter(1)}, {"resource": former}], "link": []}
    respx.get(f"{HAPI}/Encounter").mock(return_value=httpx.Response(200, json=page))

    rows, skipped = extract.admission_rows(HAPI, {"hapi-1"})

    expect.equal([row["encounter_id"] for row in rows], ["encounter-1"])
    expect.equal(skipped, {"without_admission": 0, "outside_cohort": 1, "other_signal": 0})


def test_facilities_keep_only_the_cohort_facilities() -> None:
    hospitals = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Organization", "id": "hospital-1", "name": "General Hospital", "address": [{"city": "Olympia", "state": "WA"}]}},
            {"resource": {"resourceType": "Organization", "id": "clinic-9", "name": "Unused Clinic", "address": [{"city": "Tacoma", "state": "WA"}]}},
        ],
    }

    rows = extract.facility_rows(hospitals, {"hospital-1", "synthea-fallback-facility"})

    expect.equal(
        rows,
        [
            {"facility_id": "hospital-1", "facility_name": "General Hospital", "city": "Olympia", "state": "WA"},
            {"facility_id": "synthea-fallback-facility", "facility_name": "Regional General Hospital", "city": None, "state": None},
        ],
    )


@respx.mock
def test_each_signal_keeps_only_its_own_encounters() -> None:
    null_control = encounter(5)
    null_control["identifier"] = [{"system": SYSTEM, "value": "batch-4817263-null-1:hapi-1"}]
    page = {"resourceType": "Bundle", "entry": [{"resource": encounter(1)}, {"resource": null_control}], "link": []}
    respx.get(f"{HAPI}/Encounter").mock(return_value=httpx.Response(200, json=page))

    rows, skipped = extract.admission_rows(HAPI, {"hapi-1"})
    null_rows, null_skipped = extract.admission_rows(HAPI, {"hapi-1"}, signal="null_control")

    expect.equal([row["encounter_id"] for row in rows], ["encounter-1"])
    expect.equal(skipped["other_signal"], 1)
    expect.equal([row["encounter_id"] for row in null_rows], ["encounter-5"])
    expect.equal(null_skipped["other_signal"], 1)
