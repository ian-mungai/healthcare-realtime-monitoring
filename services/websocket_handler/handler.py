import os
from typing import Any

import boto3

CONNECTIONS_TABLE = os.getenv("CONNECTIONS_TABLE", "healthcare-realtime-websocket-connections")

dynamodb = boto3.resource("dynamodb")
connections_table = dynamodb.Table(CONNECTIONS_TABLE)


def build_response(status_code: int, message: str) -> dict[str, Any]:
    return {"statusCode": status_code, "body": message}


def handle_connect(event: dict[str, Any], connection_id: str) -> dict[str, Any]:
    query_parameters = event.get("queryStringParameters") or {}
    patient_id = query_parameters.get("patient_id")

    if not patient_id:
        return build_response(400, "patient_id is required")

    connections_table.put_item(Item={"connection_id": connection_id, "patient_id": patient_id})

    return build_response(200, "Connected")


def handle_disconnect(connection_id: str) -> dict[str, Any]:
    connections_table.delete_item(Key={"connection_id": connection_id})

    return build_response(200, "Disconnected")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_context = event.get("requestContext") or {}
    route_key = request_context.get("routeKey")
    connection_id = request_context.get("connectionId")

    if not connection_id:
        return build_response(400, "connectionId is required")

    if route_key == "$connect":
        return handle_connect(event=event, connection_id=connection_id)

    if route_key == "$disconnect":
        return handle_disconnect(connection_id=connection_id)

    return build_response(400, f"Unsupported route: {route_key}")
