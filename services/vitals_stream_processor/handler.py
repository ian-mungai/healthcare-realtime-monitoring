import base64
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from services.vitals_stream_processor.schema import validate_vitals_payload
else:
    try:
        from services.vitals_stream_processor.schema import validate_vitals_payload
    except ModuleNotFoundError:
        from schema import validate_vitals_payload

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
LATEST_VITALS_TABLE = os.getenv("LATEST_VITALS_TABLE", "healthcare-realtime-latest-vitals")
CONNECTIONS_TABLE = os.getenv("CONNECTIONS_TABLE", "healthcare-realtime-websocket-connections")
WEBSOCKET_ENDPOINT = os.getenv("WEBSOCKET_ENDPOINT", "")

METRIC_NAMESPACE = "HealthcareRealtime/Live"

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
latest_vitals_table = dynamodb.Table(LATEST_VITALS_TABLE)
connections_table = dynamodb.Table(CONNECTIONS_TABLE)

cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)


def decode_kinesis_record(record: dict[str, Any]) -> dict[str, Any]:
    encoded_data = record["kinesis"]["data"]
    decoded_data = base64.b64decode(encoded_data).decode("utf-8")
    return json.loads(decoded_data)


def to_dynamodb_item(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload), parse_float=Decimal)


def event_timestamp_epoch_ms(event_timestamp: str) -> int:
    event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    return int(event_time.timestamp() * 1000)


def write_latest_vitals(payload: dict[str, Any]) -> bool:
    patient_id = payload.get("patient_id")
    event_timestamp = payload.get("event_timestamp")

    if not patient_id:
        raise ValueError("patient_id is required")

    if not event_timestamp:
        raise ValueError("event_timestamp is required")

    incoming_epoch_ms = event_timestamp_epoch_ms(event_timestamp)

    item = to_dynamodb_item(payload)
    item["_event_timestamp_epoch_ms"] = incoming_epoch_ms

    try:
        latest_vitals_table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(#event_epoch) OR #event_epoch < :incoming_event_epoch",
            ExpressionAttributeNames={"#event_epoch": "_event_timestamp_epoch_ms"},
            ExpressionAttributeValues={":incoming_event_epoch": incoming_epoch_ms},
        )

    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"Ignoring duplicate or stale vital event for patient {patient_id} at {event_timestamp}")
            return False

        raise

    return True


def get_patient_connections(patient_id: str) -> list[str]:
    connection_ids: list[str] = []
    query_parameters: dict[str, Any] = {
        "IndexName": "patient_id-index",
        "KeyConditionExpression": Key("patient_id").eq(patient_id),
        "ProjectionExpression": "connection_id",
    }

    while True:
        response = connections_table.query(**query_parameters)

        connection_ids.extend(item["connection_id"] for item in response.get("Items", []) if item.get("connection_id"))

        last_evaluated_key = response.get("LastEvaluatedKey")

        if not last_evaluated_key:
            break

        query_parameters["ExclusiveStartKey"] = last_evaluated_key

    return connection_ids


def delete_connection(connection_id: str) -> None:
    connections_table.delete_item(Key={"connection_id": connection_id})


def emit_metrics(metric_data: list[dict[str, Any]]) -> None:
    if not metric_data:
        return

    cloudwatch.put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=metric_data)


def calculate_latency_ms(event_timestamp: str) -> float:
    event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    current_time = datetime.now(UTC)

    return max((current_time - event_time).total_seconds() * 1000, 0.0)


def push_vitals(payload: dict[str, Any]) -> tuple[int, int, int]:
    if not WEBSOCKET_ENDPOINT:
        print("WebSocket endpoint is not configured")
        return 0, 0, 0

    patient_id = payload.get("patient_id")

    if not patient_id:
        raise ValueError("patient_id is required")

    api_gateway = boto3.client("apigatewaymanagementapi", endpoint_url=WEBSOCKET_ENDPOINT)

    connection_ids = get_patient_connections(patient_id)
    message = json.dumps(payload).encode("utf-8")

    deliveries = 0
    failures = 0

    print(f"Sending vital update for patient {patient_id} to {len(connection_ids)} WebSocket connection(s)")

    for connection_id in connection_ids:
        try:
            api_gateway.post_to_connection(ConnectionId=connection_id, Data=message)

            deliveries += 1
            print(f"Sent vital update for patient {patient_id} to connection {connection_id}")

        except ClientError as error:
            status_code = error.response["ResponseMetadata"]["HTTPStatusCode"]

            print(f"WebSocket delivery failed for {connection_id}: {error}")

            if status_code == 410:
                delete_connection(connection_id)
            else:
                failures += 1

    return deliveries, failures, len(connection_ids)


def build_metric_data(payload: dict[str, Any], deliveries: int, delivery_failures: int, active_connections: int) -> list[dict[str, Any]]:
    metric_data: list[dict[str, Any]] = [
        {"MetricName": "RecordsProcessed", "Value": 1, "Unit": "Count"},
        {"MetricName": "WebSocketDeliveries", "Value": deliveries, "Unit": "Count"},
        {"MetricName": "WebSocketDeliveryFailures", "Value": delivery_failures, "Unit": "Count"},
        {"MetricName": "ActiveConnections", "Value": active_connections, "Unit": "Count"},
    ]

    event_timestamp = payload.get("event_timestamp")

    if event_timestamp:
        try:
            metric_data.append({"MetricName": "ProcessingLatencyMilliseconds", "Value": calculate_latency_ms(event_timestamp), "Unit": "Milliseconds"})
        except (TypeError, ValueError) as error:
            print(f"Unable to calculate processing latency for timestamp {event_timestamp!r}: {error}")

    return metric_data


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    batch_item_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        sequence_number = record["kinesis"]["sequenceNumber"]

        try:
            payload = decode_kinesis_record(record)

            validate_vitals_payload(payload)

            if not write_latest_vitals(payload):
                continue

            deliveries, delivery_failures, active_connections = push_vitals(payload)

            metric_data = build_metric_data(payload, deliveries, delivery_failures, active_connections)

            emit_metrics(metric_data)

        except Exception as error:
            print(f"Failed Kinesis record {sequence_number}: {error}")

            batch_item_failures.append({"itemIdentifier": sequence_number})

    return {"batchItemFailures": batch_item_failures}
