from unittest.mock import patch

from services.websocket_handler.handler import lambda_handler


@patch("services.websocket_handler.handler.connections_table")
def test_connect_stores_patient_subscription(connections_table) -> None:
    event = {"requestContext": {"routeKey": "$connect", "connectionId": "connection-123"}, "queryStringParameters": {"patient_id": "137506799"}}

    result = lambda_handler(event, None)

    assert result["statusCode"] == 200

    connections_table.put_item.assert_called_once_with(Item={"connection_id": "connection-123", "patient_id": "137506799"})


@patch("services.websocket_handler.handler.connections_table")
def test_connect_requires_patient_id(connections_table) -> None:
    event = {"requestContext": {"routeKey": "$connect", "connectionId": "connection-123"}, "queryStringParameters": {}}

    result = lambda_handler(event, None)

    assert result["statusCode"] == 400
    connections_table.put_item.assert_not_called()


@patch("services.websocket_handler.handler.connections_table")
def test_connect_handles_missing_query_parameters(connections_table) -> None:
    event = {"requestContext": {"routeKey": "$connect", "connectionId": "connection-123"}, "queryStringParameters": None}

    result = lambda_handler(event, None)

    assert result["statusCode"] == 400
    connections_table.put_item.assert_not_called()


@patch("services.websocket_handler.handler.connections_table")
def test_disconnect_removes_connection(connections_table) -> None:
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
