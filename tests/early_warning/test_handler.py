"""The early-warning endpoint: GET /patients/{patient_id}/early-warning on the vitals API.

Failure modes (written before the code):

1. A caller reads a patient the access policy does not grant: 403, as for the vitals route.
2. The model scores before the feature window has closed, on readings training never saw: until the cutoff plus a grace
   period for late readings, the response says the window is open and when it closes.
3. Each request rescores the encounter, or two requests store different scores: the first score is stored once with a
   condition and later requests return it.
4. A score stored for another model version is returned after the approved version changes: scores are kept per
   version.
5. Parameters that do not match their published checksum are used: the model is reported unavailable instead.
6. A reading exactly at the cutoff, or the stored score item, enters the window.
7. The cached vitals lack a NEWS2 parameter: NEWS2 has no total and names what is missing; the model can still score.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from services.early_warning import handler, scoring
from services.feature_window import reading_key
from testkit import expect

PRINCIPAL_ARN = "arn:aws:iam::111111111111:user/dashboard-test"
START = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PARAMETERS = {
    "model_version": "logistic-abc123",
    "feature_columns": list(scoring.FEATURES),
    "medians": [1.0] * 12,
    "means": [0.0] * 12,
    "scales": [100.0] * 12,
    "coefficients": [0.1] * 12,
    "intercept": -1.0,
}
LATEST = {
    "patient_id": "patient-01",
    "encounter_id": "encounter-1",
    "heart_rate": Decimal("70"),
    "heart_rate_event_timestamp": "2026-10-08T12:20:00Z",
    "respiratory_rate": Decimal("16"),
    "spo2": Decimal("97"),
    "systolic_bp": Decimal("120"),
    "inhaled_oxygen_concentration": Decimal("21"),
    "consciousness_level": Decimal("0"),
    "temperature": Decimal("37.0"),
}


class FakeWindowTable:
    """The window table's partition for one encounter, answering the two queries and the score writes the handler makes."""

    def __init__(self, readings: list[dict[str, Any]]) -> None:
        self.items = {item["reading"]: item for item in readings}
        self.puts = 0

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        item = self.items.get(kwargs["Key"]["reading"])
        return {"Item": item} if item else {}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        values = kwargs["ExpressionAttributeValues"]
        keys = sorted(self.items)
        if "BETWEEN" in kwargs["KeyConditionExpression"]:
            keys = [key for key in keys if values[":low"] <= key <= values[":high"]]
        else:
            keys = [key for key in keys if key < values[":before"]]
        return {"Items": [self.items[key] for key in keys][: kwargs.get("Limit", len(keys))]}

    def put_item(self, **kwargs: Any) -> None:
        item = kwargs["Item"]
        if "ConditionExpression" in kwargs and item["reading"] in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}}, "PutItem")
        self.puts += 1
        self.items[item["reading"]] = item


def window_reading(seconds: float, observation: str, **vitals: float) -> dict[str, Any]:
    timestamp = (START + timedelta(seconds=seconds)).isoformat()
    return {"reading": reading_key(timestamp, observation), "event_timestamp": timestamp, **{key: Decimal(str(value)) for key, value in vitals.items()}}


READINGS = [
    window_reading(0, "o1", heart_rate=60, respiratory_rate=12, spo2=97),
    window_reading(450, "o2", heart_rate=100, systolic_bp=110, diastolic_bp=70),
    window_reading(900, "o3", heart_rate=250),
]


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", json.dumps({PRINCIPAL_ARN: ["patient-01"]}))
    monkeypatch.setattr(handler, "MODEL_VERSION", "logistic-abc123")
    monkeypatch.setattr(handler, "load_parameters", lambda version: PARAMETERS)


def call(patient_id: str, latest: dict[str, Any] | None, window: FakeWindowTable, now: datetime) -> tuple[int, dict[str, Any]]:
    event = {"pathParameters": {"patient_id": patient_id}, "requestContext": {"authorizer": {"iam": {"userArn": PRINCIPAL_ARN}}}}
    with (
        patch.object(handler, "latest_vitals_table") as latest_table,
        patch.object(handler, "feature_window_table", window),
        patch.object(handler, "now", return_value=now),
    ):
        latest_table.get_item.return_value = {"Item": latest} if latest else {}
        result = handler.lambda_handler(event, None)
    return result["statusCode"], json.loads(result["body"])


def test_a_patient_outside_the_policy_is_refused() -> None:
    status, _ = call("patient-02", LATEST, FakeWindowTable(READINGS), START + timedelta(hours=1))
    expect.equal(status, 403)


def test_the_model_waits_for_the_window_and_its_grace_period() -> None:
    status, body = call("patient-01", LATEST, FakeWindowTable(READINGS), START + handler.scoring.WINDOW + handler.GRACE - timedelta(seconds=1))

    expect.equal(status, 200)
    expect.equal(body["model"]["status"], "window_open")
    expect.equal(body["model"]["window_closes_at"], "2026-10-08T12:15:00Z")
    expect.equal(body["news2"]["total"], 0)


def test_the_score_is_computed_once_without_the_cutoff_reading_and_reused() -> None:
    window = FakeWindowTable(READINGS)
    later = START + timedelta(hours=1)

    _, first = call("patient-01", LATEST, window, later)
    _, second = call("patient-01", LATEST, window, later)

    expected = scoring.probability(scoring.window_features([READINGS[0], READINGS[1]]).features, PARAMETERS)
    expect.equal(first["model"]["status"], "scored")
    expect.equal(abs(first["model"]["probability"] - expected) < 1e-12, True)
    expect.equal(first["model"]["readings"], 2)
    expect.equal(second["model"], first["model"])
    expect.equal(window.puts, 1)


def test_scores_are_kept_per_model_version(monkeypatch: pytest.MonkeyPatch) -> None:
    window = FakeWindowTable(READINGS)
    call("patient-01", LATEST, window, START + timedelta(hours=1))
    monkeypatch.setattr(handler, "MODEL_VERSION", "logistic-def456")
    monkeypatch.setattr(handler, "load_parameters", lambda version: {**PARAMETERS, "model_version": version, "intercept": 2.0})

    _, body = call("patient-01", LATEST, window, START + timedelta(hours=1))

    expect.equal(body["model"]["model_version"], "logistic-def456")
    expect.equal(window.puts, 2)


def test_parameters_that_fail_their_checksum_make_the_model_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(PARAMETERS).encode()

    class FakeS3:
        def get_object(self, **_: Any) -> dict[str, Any]:
            return {"Body": type("Body", (), {"read": lambda self: body})(), "Metadata": {"sha256": hashlib.sha256(b"other").hexdigest()}}

    monkeypatch.undo()
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", json.dumps({PRINCIPAL_ARN: ["patient-01"]}))
    monkeypatch.setattr(handler, "MODEL_VERSION", "logistic-abc123")
    monkeypatch.setattr(handler, "s3", FakeS3())
    handler.load_parameters.cache_clear()

    _, response = call("patient-01", LATEST, FakeWindowTable(READINGS), START + timedelta(hours=1))

    expect.equal(response["model"]["status"], "model_unavailable")


def test_news2_without_a_parameter_has_no_total_and_the_model_still_scores() -> None:
    latest = {key: value for key, value in LATEST.items() if key != "temperature"}

    _, body = call("patient-01", latest, FakeWindowTable(READINGS), START + timedelta(hours=1))

    expect.equal((body["news2"]["total"], body["news2"]["missing"]), (None, ["temperature"]))
    expect.equal(body["model"]["status"], "scored")
