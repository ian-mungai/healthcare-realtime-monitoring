import os
from typing import Any

import boto3

CONNECTIONS_TABLE = os.getenv("CONNECTIONS_TABLE", "healthcare-realtime-websocket-connections")

dynamodb = boto3.resource("dynamodb")
connections_table = dynamodb.Table(CONNECTIONS_TABLE)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    route_key = event["requestContext"]["routeKey"]
    connection_id = event["requestContext"]["connectionId"]

    if route_key == "$connect":
        connections_table.put_item(Item={"connection_id": connection_id})
        return {"statusCode": 200}

    if route_key == "$disconnect":
        connections_table.delete_item(Key={"connection_id": connection_id})
        return {"statusCode": 200}

    return {"statusCode": 200}
