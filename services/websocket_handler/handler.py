import os
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from services.realtime_authorization import get_principal_arn, is_patient_authorized
else:
    try:
        from services.realtime_authorization import get_principal_arn, is_patient_authorized
    except ModuleNotFoundError:
        from authorization import get_principal_arn, is_patient_authorized

CONNECTIONS_TABLE = os.getenv("CONNECTIONS_TABLE", "healthcare-realtime-websocket-connections")
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
connections_table = dynamodb.Table(CONNECTIONS_TABLE)


def build_response(status_code: int, message: str) -> dict[str, Any]:
    return {"statusCode": status_code, "body": message}


def get_connections_table() -> Any:
    return connections_table


def handle_connect(event: dict[str, Any], connection_id: str) -> dict[str, Any]:
    query_parameters = event.get("queryStringParameters") or {}
    patient_id = query_parameters.get("patient_id")

    if not patient_id:
        return build_response(400, "patient_id is required")

    if not is_patient_authorized(event, patient_id):
        return build_response(403, "Access to this patient is not authorized")

    get_connections_table().put_item(Item={"connection_id": connection_id, "patient_id": patient_id, "principal_arn": get_principal_arn(event)})

    return build_response(200, "Connected")


def handle_disconnect(connection_id: str) -> dict[str, Any]:
    get_connections_table().delete_item(Key={"connection_id": connection_id})

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
