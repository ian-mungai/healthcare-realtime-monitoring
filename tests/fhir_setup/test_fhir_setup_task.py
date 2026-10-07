"""The FHIR setup task against a fake HAPI server and a fake S3 bucket.

Covers the scenarios in docs/fhir-setup-tasks.md that can run without AWS: a first and repeated load, missing or too few
bundles, a HAPI error, a first and repeated registration, a missing secret and a missing setting, and the daily
reference extract.

Failure modes of the reference extract (written before the code):

1. The extract runs before the cohort is loaded (no resource map in S3): stop before writing anything.
2. A rerun must not leave earlier rows behind: each table is one object at a fixed key, replaced whole.
3. The null control's or a former cohort's encounters must not reach AWS admissions: they are skipped and counted.
4. The split groups must match the waveform record each patient gets from the simulator (cohort position order).
5. The reference files must not land under the raw prefix the Glue job reads recursively: they use their own prefix. The deployed run and
its report under artifacts/e2e/fhir_setup/ remain the end-to-end proof.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
import respx
from botocore.exceptions import ClientError

from jobs.fhir_setup import task
from testkit import expect

HAPI = "http://hapi.example.invalid/fhir"
BUCKET = "example-bucket"
PREFIX = "seed/synthea/fhir"
MAP_KEY = "config/vitals_simulator/fhir_resource_map.json"
WEBHOOK_URL = "https://webhook.example.invalid/fhir"
SYSTEM = "https://github.com/synthetichealth/synthea"
SAMPLE_CREDENTIAL = "sample-credential"


class FakeS3:
    """Keeps objects in memory and implements the four calls the task makes."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.uploads: list[str] = []

    def get_paginator(self, name: str) -> FakeS3:
        expect.equal(name, "list_objects_v2")
        return self

    def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, list[dict[str, str]]]]:
        return [{"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]}]

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        if key not in self.objects:
            # boto3 raises ClientError with a 404 for a missing object.
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        Path(filename).write_bytes(self.objects[key])

    def put_object(self, Bucket: str, Key: str, Body: bytes, ServerSideEncryption: str, ContentType: str) -> None:
        expect.equal(ServerSideEncryption, "AES256")
        self.objects[Key] = Body
        self.uploads.append(Key)

    def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs: dict[str, str]) -> None:
        expect.equal(ExtraArgs, {"ServerSideEncryption": "AES256"})
        self.objects[key] = Path(filename).read_bytes()
        self.uploads.append(key)


class FakeHapi:
    """Stores created Patients, Encounters and Subscriptions and answers identifier and endpoint searches."""

    def __init__(self, fail_on: str | None = None, unready_responses: int = 0) -> None:
        self.resources: dict[str, dict[str, dict]] = {"Patient": {}, "Encounter": {}, "Subscription": {}}
        self.creates = 0
        self.fail_on = fail_on
        # A new HAPI task answers 502 through the load balancer until its target passes the health check.
        self.unready_responses = unready_responses
        self.metadata_requests = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/fhir/").split("/")
        kind = path[0]
        if kind == "metadata":
            self.metadata_requests += 1
            if self.metadata_requests <= self.unready_responses:
                return httpx.Response(502)
            return httpx.Response(200, json={"resourceType": "CapabilityStatement"})
        if request.method == "POST":
            if kind == self.fail_on:
                return httpx.Response(500, json={"resourceType": "OperationOutcome"})
            resource = json.loads(request.content)
            self.creates += 1
            resource["id"] = f"{kind.lower()}-{self.creates}"
            self.resources[kind][resource["id"]] = resource
            return httpx.Response(201, json=resource)
        if len(path) == 2:
            return httpx.Response(200, json=self.resources[kind][path[1]])
        return httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": r} for r in self.search(kind, request.url.params)]})

    def search(self, kind: str, params: httpx.QueryParams) -> list[dict]:
        if "identifier" in params:
            system, value = params["identifier"].split("|", 1)
            if not value:
                # identifier=system| matches every resource with an identifier of that system, as on HAPI.
                return [r for r in self.resources[kind].values() if any(i.get("system") == system for i in r.get("identifier", []))]
            return [r for r in self.resources[kind].values() if any(i.get("value") == value for i in r.get("identifier", []))]
        return [r for r in self.resources[kind].values() if r.get("channel", {}).get("endpoint") == params.get("url")]


def bundle(number: int) -> bytes:
    """One Synthea-style patient bundle with a patient and one encounter."""
    patient = {"resourceType": "Patient", "id": f"p{number}", "identifier": [{"system": SYSTEM, "value": f"p{number}"}]}
    encounter = {
        "resourceType": "Encounter",
        "id": f"e{number}",
        "identifier": [{"system": SYSTEM, "value": f"e{number}"}],
        "subject": {"reference": f"urn:uuid:p{number}"},
        "period": {"start": "2026-09-01T10:00:00Z"},
    }
    entries = [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in (patient, encounter)]
    return json.dumps({"resourceType": "Bundle", "type": "transaction", "entry": entries}).encode()


def bundles(count: int) -> dict[str, bytes]:
    return {f"{PREFIX}/patient_{number:02d}.json": bundle(number) for number in range(count)}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "FHIR_BASE_URL": HAPI,
        "FHIR_RESOURCE_MAP_S3_BUCKET": BUCKET,
        "FHIR_RESOURCE_MAP_S3_KEY": MAP_KEY,
        "SEED_BUNDLES_S3_PREFIX": PREFIX,
        "FHIR_WEBHOOK_URL": WEBHOOK_URL,
    }.items():
        monkeypatch.setenv(name, value)


class FakeClock:
    """Advances only when the task sleeps, so readiness waits finish instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def run_load(monkeypatch: pytest.MonkeyPatch, s3: FakeS3, hapi: FakeHapi, clock: FakeClock | None = None) -> int:
    clock = clock or FakeClock()
    monkeypatch.setattr(task.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(task.time, "sleep", clock.sleep)
    monkeypatch.setattr(task.boto3, "client", lambda service: s3)
    with respx.mock(assert_all_called=False) as router:
        router.route(url__regex=re.escape(HAPI) + r"/.*").mock(side_effect=hapi.handle)
        return task.main(["load"])


def test_first_load_seeds_ten_patients_and_publishes_the_map(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi = FakeS3(bundles(12)), FakeHapi()

    expect.equal(run_load(monkeypatch, s3, hapi), 0)

    expect.equal((len(hapi.resources["Patient"]), len(hapi.resources["Encounter"])), (10, 10))
    expect.equal(s3.uploads, [MAP_KEY])
    expect.equal(len(json.loads(s3.objects[MAP_KEY])["cohort"]), 10)


def test_repeated_load_reuses_resources_and_keeps_the_ids(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi = FakeS3(bundles(10)), FakeHapi()
    run_load(monkeypatch, s3, hapi)
    first_map = s3.objects[MAP_KEY]

    expect.equal(run_load(monkeypatch, s3, hapi), 0)

    expect.equal(hapi.creates, 20)
    expect.equal(s3.objects[MAP_KEY], first_map)


def test_load_without_bundles_fails_before_touching_hapi(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi = FakeS3({}), FakeHapi()

    expect.equal(run_load(monkeypatch, s3, hapi), 1)

    expect.equal((hapi.creates, s3.uploads), (0, []))


def test_load_with_fewer_than_ten_bundles_fails_without_a_map(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi = FakeS3(bundles(9)), FakeHapi()

    expect.equal(run_load(monkeypatch, s3, hapi), 1)

    expect.equal((hapi.creates, s3.uploads), (0, []))


def test_hapi_error_fails_the_load_without_a_map(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi = FakeS3(bundles(10)), FakeHapi(fail_on="Encounter")

    expect.equal(run_load(monkeypatch, s3, hapi), 1)

    expect.equal(s3.uploads, [])


def test_load_waits_for_hapi_to_pass_its_health_check(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi, clock = FakeS3(bundles(10)), FakeHapi(unready_responses=2), FakeClock()

    expect.equal(run_load(monkeypatch, s3, hapi, clock), 0)

    expect.equal(hapi.metadata_requests, 3)
    expect.equal(len(clock.sleeps), 2)
    expect.equal(s3.uploads, [MAP_KEY])


def test_load_stops_when_hapi_never_becomes_ready(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi, clock = FakeS3(bundles(10)), FakeHapi(unready_responses=10_000), FakeClock()

    expect.equal(run_load(monkeypatch, s3, hapi, clock), 1)

    if clock.now > task.HAPI_READY_TIMEOUT_SECONDS + task.HAPI_READY_POLL_SECONDS:
        expect.fail("expected: the wait stops at the readiness limit")
    expect.equal((hapi.creates, s3.uploads), (0, []))


def run_register(monkeypatch: pytest.MonkeyPatch, hapi: FakeHapi, credential: str | None = SAMPLE_CREDENTIAL) -> int:
    def webhook_secret() -> str:
        if credential is None:
            raise RuntimeError("FHIR_WEBHOOK_SECRET_ID is not configured")
        return credential

    monkeypatch.setattr("services.fhir_webhook.app.config.get_webhook_secret", webhook_secret)
    with respx.mock(assert_all_called=False) as router:
        router.route(url__regex=re.escape(HAPI) + r"/.*").mock(side_effect=hapi.handle)
        return task.main(["register"])


def test_first_registration_creates_one_subscription(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    hapi = FakeHapi()

    expect.equal(run_register(monkeypatch, hapi), 0)

    subscriptions = list(hapi.resources["Subscription"].values())
    expect.equal(len(subscriptions), 1)
    expect.equal(subscriptions[0]["channel"]["endpoint"], WEBHOOK_URL)


def test_repeated_registration_reuses_the_subscription(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    hapi = FakeHapi()
    run_register(monkeypatch, hapi)

    expect.equal(run_register(monkeypatch, hapi), 0)

    expect.equal(len(hapi.resources["Subscription"]), 1)


def test_registration_without_a_secret_fails_before_calling_hapi(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    hapi = FakeHapi()

    expect.equal(run_register(monkeypatch, hapi, credential=None), 1)

    expect.equal(hapi.creates, 0)


def test_missing_setting_is_named_and_fails(settings: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("FHIR_RESOURCE_MAP_S3_BUCKET")

    expect.equal(task.main(["load"]), 1)

    expect.is_in("FHIR_RESOURCE_MAP_S3_BUCKET is not configured", caplog.text)


REFERENCE_PREFIX = "reference/cohort"
RUN_SYSTEM = "https://example.org/fhir/identifier/vitals-simulator-encounter"


def admitted_encounter(patient_id: str, run_id: str) -> dict:
    return {
        "resourceType": "Encounter",
        "identifier": [{"system": RUN_SYSTEM, "value": f"{run_id}:{patient_id}"}],
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": "2026-06-01T08:00:00+00:00", "end": "2026-06-03T08:00:00+00:00"},
        "reasonCode": [
            {"coding": [{"system": "http://snomed.info/sct", "code": "233604007", "display": "Pneumonia (disorder)"}], "text": "simulator_fallback"}
        ],
        "serviceProvider": {"identifier": {"value": "hospital-1"}, "display": "General Hospital"},
        "location": [{"location": {"display": "Step-down unit"}}],
        "participant": [
            {
                "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType", "code": "ATND"}]}],
                "individual": {"identifier": {"system": "http://hl7.org/fhir/sid/us-npi", "value": "1234567893"}, "display": "Example Attending"},
            }
        ],
    }


def run_reference(monkeypatch: pytest.MonkeyPatch, s3: FakeS3, hapi: FakeHapi) -> int:
    monkeypatch.setenv("COHORT_REFERENCE_S3_PREFIX", REFERENCE_PREFIX)
    monkeypatch.setattr(task.boto3, "client", lambda service: s3)
    with respx.mock(assert_all_called=False) as router:
        router.route(url__regex=re.escape(HAPI) + r"/.*").mock(side_effect=hapi.handle)
        return task.main(["reference"])


def table_rows(s3: FakeS3, table: str) -> list[dict]:
    return [json.loads(line) for line in s3.objects[f"{REFERENCE_PREFIX}/{table}/{table}.json"].decode().splitlines()]


def test_reference_writes_each_table_once_and_keeps_only_the_cohorts_study_encounters(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi = FakeS3({**bundles(10), f"{PREFIX}/hospitalInformation1.json": b'{"resourceType": "Bundle", "entry": []}'}), FakeHapi()
    run_load(monkeypatch, s3, hapi)
    patients = sorted(hapi.resources["Patient"])
    for index, encounter in enumerate(
        [admitted_encounter(patient, "live-run-1") for patient in patients]
        + [admitted_encounter(patients[0], "batch-4817263-null-1"), admitted_encounter("former-patient", "live-run-1")]
    ):
        hapi.resources["Encounter"][f"simulated-{index}"] = {**encounter, "id": f"simulated-{index}"}

    expect.equal(run_reference(monkeypatch, s3, hapi), 0)
    first = {key: value for key, value in s3.objects.items() if key.startswith(REFERENCE_PREFIX)}
    expect.equal(run_reference(monkeypatch, s3, hapi), 0)

    expect.equal({key: value for key, value in s3.objects.items() if key.startswith(REFERENCE_PREFIX)}, first)
    expect.equal(
        sorted(first),
        sorted(
            f"{REFERENCE_PREFIX}/{table}/{table}.json"
            for table in ("fhir_patients", "patient_payer_history", "facilities", "admissions", "patient_split_groups")
        ),
    )
    expect.equal(len(table_rows(s3, "admissions")), 10)
    expect.equal(len(table_rows(s3, "fhir_patients")), 10)
    groups = table_rows(s3, "patient_split_groups")
    expect.equal([row["split_group"] for row in groups], [f"bidmc{number:02d}" for number in range(1, 11)])


def test_reference_without_a_resource_map_writes_nothing(settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    s3, hapi = FakeS3(bundles(10)), FakeHapi()

    expect.equal(run_reference(monkeypatch, s3, hapi), 1)

    expect.equal(s3.uploads, [])
