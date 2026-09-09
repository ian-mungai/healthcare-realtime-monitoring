import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from services.vitals_api.handler import lambda_handler

PRINCIPAL_ARN = "arn:aws:iam::111111111111:user/dashboard-test"


@pytest.fixture(autouse=True)
def patient_access_policy(monkeypatch) -> None:
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", json.dumps({PRINCIPAL_ARN: ["137506799", "missing"]}))


def event_for(patient_id: str) -> dict:
    return {"pathParameters": {"patient_id": patient_id}, "requestContext": {"authorizer": {"iam": {"userArn": PRINCIPAL_ARN}}}}


@patch("services.vitals_api.handler.get_latest_vitals_table")
def test_lambda_handler_returns_latest_vitals(get_latest_vitals_table) -> None:
    latest_vitals_table = get_latest_vitals_table.return_value
    latest_vitals_table.get_item.return_value = {
        "Item": {
            "patient_id": "137506799",
            "source_record_id": "bidmc01n",
            "event_timestamp": "2026-08-28T17:00:00Z",
            "heart_rate": Decimal("96"),
            "heart_rate_event_timestamp": "2026-08-28T17:00:02Z",
            "respiratory_rate": Decimal("20"),
            "spo2": Decimal("98"),
            "systolic_bp": Decimal("120"),
            "diastolic_bp": Decimal("78"),
            "_event_timestamp_epoch_ms": Decimal("1787936400000"),
            "_replay_attempt": Decimal("1"),
        }
    }

    result = lambda_handler(event_for("137506799"), None)

    body = json.loads(result["body"])

    assert result["statusCode"] == 200
    assert body["patient_id"] == "137506799"
    assert body["heart_rate"] == 96.0
    assert body["event_timestamp"] == "2026-08-28T17:00:02Z"
    assert "_event_timestamp_epoch_ms" not in body
    assert "_replay_attempt" not in body
    assert "Access-Control-Allow-Origin" not in result["headers"]


@patch("services.vitals_api.handler.get_latest_vitals_table")
def test_lambda_handler_returns_not_found(get_latest_vitals_table) -> None:
    latest_vitals_table = get_latest_vitals_table.return_value
    latest_vitals_table.get_item.return_value = {}

    result = lambda_handler(event_for("missing"), None)

    assert result["statusCode"] == 404


def test_lambda_handler_requires_patient_id() -> None:
    result = lambda_handler({"pathParameters": {}}, None)

    assert result["statusCode"] == 400


@patch("services.vitals_api.handler.get_latest_vitals_table")
def test_lambda_handler_denies_unauthorized_patient(get_latest_vitals_table) -> None:
    result = lambda_handler(event_for("not-authorized"), None)

    assert result["statusCode"] == 403
    get_latest_vitals_table.assert_not_called()
