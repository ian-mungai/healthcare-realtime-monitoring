import base64
import json
import os
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

LATEST_VITALS_TABLE = os.getenv("LATEST_VITALS_TABLE", "healthcare-realtime-latest-vitals")
CONNECTIONS_TABLE = os.getenv("CONNECTIONS_TABLE", "healthcare-realtime-websocket-connections")
WEBSOCKET_ENDPOINT = os.getenv("WEBSOCKET_ENDPOINT", "")

dynamodb = boto3.resource("dynamodb")
latest_vitals_table = dynamodb.Table(LATEST_VITALS_TABLE)
connections_table = dynamodb.Table(CONNECTIONS_TABLE)


def decode_kinesis_record(record: dict[str, Any]) -> dict[str, Any]:
    encoded_data = record["kinesis"]["data"]
    decoded_data = base64.b64decode(encoded_data).decode("utf-8")
    return json.loads(decoded_data)


def to_dynamodb_item(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload), parse_float=Decimal)


def write_latest_vitals(payload: dict[str, Any]) -> None:
    if "patient_id" not in payload:
        raise ValueError("patient_id is required")

    latest_vitals_table.put_item(Item=to_dynamodb_item(payload))


def get_connection_ids() -> list[str]:
    response = connections_table.scan(ProjectionExpression="connection_id")
    return [item["connection_id"] for item in response.get("Items", [])]


def delete_connection(connection_id: str) -> None:
    connections_table.delete_item(Key={"connection_id": connection_id})


def push_vitals(payload: dict[str, Any]) -> None:
    if not WEBSOCKET_ENDPOINT:
        return

    api_gateway = boto3.client("apigatewaymanagementapi", endpoint_url=WEBSOCKET_ENDPOINT)
    message = json.dumps(payload).encode("utf-8")

    for connection_id in get_connection_ids():
        try:
            api_gateway.post_to_connection(ConnectionId=connection_id, Data=message)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] == 410:
                delete_connection(connection_id)
                continue

            raise


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    batch_item_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        sequence_number = record["kinesis"]["sequenceNumber"]

        try:
            payload = decode_kinesis_record(record)
            write_latest_vitals(payload)
            push_vitals(payload)
        except Exception:
            batch_item_failures.append({"itemIdentifier": sequence_number})

    return {"batchItemFailures": batch_item_failures}
