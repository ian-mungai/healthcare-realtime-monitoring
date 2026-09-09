import json
from unittest.mock import patch

import pytest

from services.websocket_handler.handler import lambda_handler

PRINCIPAL_ARN = "arn:aws:sts::111111111111:assumed-role/dashboard-role/test-session"


@pytest.fixture(autouse=True)
def patient_access_policy(monkeypatch) -> None:
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", json.dumps({"arn:aws:sts::111111111111:assumed-role/dashboard-role/*": ["137506799"]}))


def connect_event(patient_id: str | None) -> dict:
    return {
        "requestContext": {"routeKey": "$connect", "connectionId": "connection-123", "identity": {"userArn": PRINCIPAL_ARN}},
        "queryStringParameters": {"patient_id": patient_id} if patient_id else {},
    }


@patch("services.websocket_handler.handler.get_connections_table")
def test_connect_stores_patient_subscription(get_connections_table) -> None:
    connections_table = get_connections_table.return_value
    event = connect_event("137506799")

    result = lambda_handler(event, None)

    assert result["statusCode"] == 200

    connections_table.put_item.assert_called_once_with(Item={"connection_id": "connection-123", "patient_id": "137506799", "principal_arn": PRINCIPAL_ARN})


@patch("services.websocket_handler.handler.get_connections_table")
def test_connect_requires_patient_id(get_connections_table) -> None:
    connections_table = get_connections_table.return_value
    event = connect_event(None)

    result = lambda_handler(event, None)

    assert result["statusCode"] == 400
    connections_table.put_item.assert_not_called()


@patch("services.websocket_handler.handler.get_connections_table")
def test_connect_handles_missing_query_parameters(get_connections_table) -> None:
    connections_table = get_connections_table.return_value
    event = {"requestContext": {"routeKey": "$connect", "connectionId": "connection-123"}, "queryStringParameters": None}

    result = lambda_handler(event, None)

    assert result["statusCode"] == 400
    connections_table.put_item.assert_not_called()


@patch("services.websocket_handler.handler.get_connections_table")
def test_connect_denies_unauthorized_patient(get_connections_table) -> None:
    result = lambda_handler(connect_event("not-authorized"), None)

    assert result["statusCode"] == 403
    get_connections_table.assert_not_called()


@patch("services.websocket_handler.handler.get_connections_table")
def test_disconnect_removes_connection(get_connections_table) -> None:
    connections_table = get_connections_table.return_value
    event = {"requestContext": {"routeKey": "$disconnect", "connectionId": "connection-123"}}

    result = lambda_handler(event, None)

    assert result["statusCode"] == 200

    connections_table.delete_item.assert_called_once_with(Key={"connection_id": "connection-123"})


def test_missing_connection_id_returns_bad_request() -> None:
    event = {"requestContext": {"routeKey": "$connect"}, "queryStringParameters": {"patient_id": "137506799"}}

    result = lambda_handler(event, None)

    assert result["statusCode"] == 400


def test_unsupported_route_returns_bad_request() -> None:
    event = {"requestContext": {"routeKey": "unsupported", "connectionId": "connection-123"}}

    result = lambda_handler(event, None)

    assert result["statusCode"] == 400
