import json
from decimal import Decimal
from unittest.mock import patch

from services.vitals_api.handler import lambda_handler


@patch("services.vitals_api.handler.latest_vitals_table")
def test_lambda_handler_returns_latest_vitals(latest_vitals_table) -> None:
    latest_vitals_table.get_item.return_value = {
        "Item": {
            "patient_id": "137506799",
            "source_record_id": "bidmc01n",
            "event_timestamp": "2026-08-28T17:00:00Z",
            "heart_rate": Decimal("96"),
            "respiratory_rate": Decimal("20"),
            "spo2": Decimal("98"),
            "systolic_bp": Decimal("120"),
            "diastolic_bp": Decimal("78"),
        }
    }

    result = lambda_handler({"pathParameters": {"patient_id": "137506799"}}, None)

    body = json.loads(result["body"])

    assert result["statusCode"] == 200
    assert body["patient_id"] == "137506799"
    assert body["heart_rate"] == 96.0


@patch("services.vitals_api.handler.latest_vitals_table")
def test_lambda_handler_returns_not_found(latest_vitals_table) -> None:
    latest_vitals_table.get_item.return_value = {}

    result = lambda_handler({"pathParameters": {"patient_id": "missing"}}, None)

    assert result["statusCode"] == 404


def test_lambda_handler_requires_patient_id() -> None:
    result = lambda_handler({"pathParameters": {}}, None)

    assert result["statusCode"] == 400
