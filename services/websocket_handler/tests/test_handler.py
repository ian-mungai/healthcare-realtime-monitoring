from unittest.mock import patch

from services.websocket_handler.handler import lambda_handler


@patch("services.websocket_handler.handler.connections_table")
def test_connect_stores_connection(connections_table) -> None:
    event = {"requestContext": {"routeKey": "$connect", "connectionId": "connection-123"}}

    result = lambda_handler(event, None)

    connections_table.put_item.assert_called_once_with(Item={"connection_id": "connection-123"})
    assert result == {"statusCode": 200}


@patch("services.websocket_handler.handler.connections_table")
def test_disconnect_removes_connection(connections_table) -> None:
    event = {"requestContext": {"routeKey": "$disconnect", "connectionId": "connection-123"}}

    result = lambda_handler(event, None)

    connections_table.delete_item.assert_called_once_with(Key={"connection_id": "connection-123"})
    assert result == {"statusCode": 200}
