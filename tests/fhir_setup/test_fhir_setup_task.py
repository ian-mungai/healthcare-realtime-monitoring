"""The FHIR setup task against a fake HAPI server and a fake S3 bucket.

Covers the scenarios in docs/fhir-setup-tasks.md that can run without AWS: a first and repeated load, missing or too few
bundles, a HAPI error, a first and repeated registration, a missing secret and a missing setting. The deployed run and
its report under artifacts/e2e/fhir_setup/ remain the end-to-end proof.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
import respx

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
        Path(filename).write_bytes(self.objects[key])

    def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs: dict[str, str]) -> None:
        expect.equal(ExtraArgs, {"ServerSideEncryption": "AES256"})
        self.objects[key] = Path(filename).read_bytes()
        self.uploads.append(key)


class FakeHapi:
    """Stores created Patients, Encounters and Subscriptions and answers identifier and endpoint searches."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.resources: dict[str, dict[str, dict]] = {"Patient": {}, "Encounter": {}, "Subscription": {}}
        self.creates = 0
        self.fail_on = fail_on

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/fhir/").split("/")
        kind = path[0]
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
            value = params["identifier"].split("|", 1)[1]
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


def run_load(monkeypatch: pytest.MonkeyPatch, s3: FakeS3, hapi: FakeHapi) -> int:
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
