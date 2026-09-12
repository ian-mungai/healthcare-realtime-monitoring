import base64
import binascii
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from services.vitals_stream_processor.schema import PermanentRecordError, validate_vitals_payload
else:
    try:
        from services.vitals_stream_processor.schema import PermanentRecordError, validate_vitals_payload
    except ModuleNotFoundError:
        from schema import PermanentRecordError, validate_vitals_payload

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
LATEST_VITALS_TABLE = os.getenv("LATEST_VITALS_TABLE", "healthcare-realtime-latest-vitals")
LOAD_TEST_RESULTS_TABLE = os.getenv("LOAD_TEST_RESULTS_TABLE", "healthcare-realtime-load-test-results")
CONNECTIONS_TABLE = os.getenv("CONNECTIONS_TABLE", "healthcare-realtime-websocket-connections")
IDEMPOTENCY_TABLE = os.getenv("IDEMPOTENCY_TABLE", "healthcare-realtime-processed-observations")
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "604800"))
IDEMPOTENCY_LEASE_SECONDS = int(os.getenv("IDEMPOTENCY_LEASE_SECONDS", "60"))
WEBSOCKET_ENDPOINT = os.getenv("WEBSOCKET_ENDPOINT", "")

METRIC_NAMESPACE = "HealthcareRealtime/Live"
LOAD_TEST_METRIC_NAMESPACE = "HealthcareRealtime/LoadTest"

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
latest_vitals_table = dynamodb.Table(LATEST_VITALS_TABLE)
load_test_results_table = dynamodb.Table(LOAD_TEST_RESULTS_TABLE)
connections_table = dynamodb.Table(CONNECTIONS_TABLE)
idempotency_table = dynamodb.Table(IDEMPOTENCY_TABLE)

cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)

VITAL_FIELDS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp")


def decode_kinesis_record(record: dict[str, Any]) -> dict[str, Any]:
    encoded_data = record["kinesis"]["data"]
    if not isinstance(encoded_data, str):
        raise PermanentRecordError("Kinesis record data must be a base64-encoded string")

    try:
        decoded_data = base64.b64decode(encoded_data, validate=True).decode("utf-8")
        payload = json.loads(decoded_data)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PermanentRecordError("Kinesis record data must contain a valid UTF-8 JSON object") from error

    if not isinstance(payload, dict):
        raise PermanentRecordError("Kinesis record data must contain a JSON object")

    return payload


def to_dynamodb_item(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload), parse_float=Decimal)


def event_timestamp_epoch_ms(event_timestamp: str) -> int:
    event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    return int(event_time.timestamp() * 1000)


def claim_observation(payload: dict[str, Any]) -> str | None:
    observation_id = payload["observation_id"]
    now_epoch = int(datetime.now(UTC).timestamp())
    claim_token = str(uuid4())

    try:
        idempotency_table.put_item(
            Item={
                "observation_id": observation_id,
                "status": "processing",
                "claim_token": claim_token,
                "lease_expires_at": now_epoch + IDEMPOTENCY_LEASE_SECONDS,
                "expires_at": now_epoch + IDEMPOTENCY_TTL_SECONDS,
            },
            ConditionExpression="attribute_not_exists(observation_id) OR (#status = :processing AND #lease_expires_at < :now_epoch)",
            ExpressionAttributeNames={"#status": "status", "#lease_expires_at": "lease_expires_at"},
            ExpressionAttributeValues={":processing": "processing", ":now_epoch": now_epoch},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"Skipping duplicate observation {observation_id}")
            return None
        raise

    return claim_token


def complete_observation_claim(observation_id: str, claim_token: str) -> None:
    expires_at = int(datetime.now(UTC).timestamp()) + IDEMPOTENCY_TTL_SECONDS
    idempotency_table.update_item(
        Key={"observation_id": observation_id},
        UpdateExpression="SET #status = :complete, expires_at = :expires_at REMOVE #claim_token, #lease_expires_at",
        ConditionExpression="#claim_token = :claim_token",
        ExpressionAttributeNames={"#status": "status", "#claim_token": "claim_token", "#lease_expires_at": "lease_expires_at"},
        ExpressionAttributeValues={":complete": "complete", ":expires_at": expires_at, ":claim_token": claim_token},
    )


def release_observation_claim(observation_id: str, claim_token: str) -> None:
    idempotency_table.delete_item(
        Key={"observation_id": observation_id},
        ConditionExpression="#claim_token = :claim_token",
        ExpressionAttributeNames={"#claim_token": "claim_token"},
        ExpressionAttributeValues={":claim_token": claim_token},
    )


def write_latest_vitals(payload: dict[str, Any]) -> bool:
    patient_id = payload.get("patient_id")
    event_timestamp = payload.get("event_timestamp")

    if not patient_id:
        raise ValueError("patient_id is required")

    if not event_timestamp:
        raise ValueError("event_timestamp is required")

    incoming_epoch_ms = event_timestamp_epoch_ms(event_timestamp)

    item = to_dynamodb_item(payload)
    update_values: dict[str, Any] = {key: item[key] for key in ("schema_version", "source", "source_record_id", "encounter_id") if key in item}
    present_vitals = [field for field in VITAL_FIELDS if field in item]

    for field in present_vitals:
        update_values[field] = item[field]
        update_values[f"{field}_event_timestamp"] = event_timestamp
        update_values[f"_{field}_event_timestamp_epoch_ms"] = incoming_epoch_ms

    expression_names = {f"#field_{index}": key for index, key in enumerate(update_values)}
    expression_values = {f":value_{index}": value for index, value in enumerate(update_values.values())}
    update_expression = "SET " + ", ".join(f"#field_{index} = :value_{index}" for index in range(len(update_values)))
    legacy_fields = ("event_timestamp", "_event_timestamp_epoch_ms", "_replay_attempt")
    for index, field in enumerate(legacy_fields):
        expression_names[f"#legacy_field_{index}"] = field
    update_expression += " REMOVE " + ", ".join(f"#legacy_field_{index}" for index in range(len(legacy_fields)))

    expression_values[":incoming_event_epoch"] = incoming_epoch_ms
    freshness_conditions = []
    for index, field in enumerate(present_vitals):
        epoch_name = f"#event_epoch_{index}"
        expression_names[epoch_name] = f"_{field}_event_timestamp_epoch_ms"
        freshness_conditions.append(f"(attribute_not_exists({epoch_name}) OR {epoch_name} <= :incoming_event_epoch)")

    try:
        latest_vitals_table.update_item(
            Key={"patient_id": patient_id},
            UpdateExpression=update_expression,
            ConditionExpression=" AND ".join(freshness_conditions),
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
        )

    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"Ignoring stale vital event for patient {patient_id} at {event_timestamp}")
            return False

        raise

    return True


def write_load_test_result(payload: dict[str, Any]) -> None:
    observation_id = payload.get("observation_id")

    if not observation_id:
        raise ValueError("observation_id is required")

    processed_at = datetime.now(UTC)
    item = to_dynamodb_item(payload)
    item["processed_at"] = processed_at.isoformat().replace("+00:00", "Z")
    item["expires_at"] = int(processed_at.timestamp()) + 86400

    load_test_results_table.put_item(Item=item)


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


def emit_metrics(metric_data: list[dict[str, Any]], namespace: str = METRIC_NAMESPACE) -> None:
    if not metric_data:
        return

    cloudwatch.put_metric_data(Namespace=namespace, MetricData=metric_data)


def calculate_latency_ms(event_timestamp: str) -> float:
    event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    current_time = datetime.now(UTC)

    return max((current_time - event_time).total_seconds() * 1000, 0.0)


@lru_cache(maxsize=1)
def get_api_gateway_client() -> Any:
    return boto3.client("apigatewaymanagementapi", region_name=AWS_REGION, endpoint_url=WEBSOCKET_ENDPOINT)


def push_vitals(payload: dict[str, Any]) -> tuple[int, int, int]:
    if not WEBSOCKET_ENDPOINT:
        print("WebSocket endpoint is not configured")
        return 0, 0, 0

    patient_id = payload.get("patient_id")

    if not patient_id:
        raise ValueError("patient_id is required")

    api_gateway = get_api_gateway_client()

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
    metrics_by_namespace: dict[str, list[dict[str, Any]]] = {}

    for record in event.get("Records", []):
        sequence_number = record["kinesis"]["sequenceNumber"]
        claimed_observation_id: str | None = None
        claim_token: str | None = None

        try:
            payload = decode_kinesis_record(record)

            validate_vitals_payload(payload)

            is_load_test = payload.get("source") == "load_test"
            metric_namespace = LOAD_TEST_METRIC_NAMESPACE if is_load_test else METRIC_NAMESPACE

            claim_token = claim_observation(payload)
            if claim_token is None:
                metrics_by_namespace.setdefault(metric_namespace, []).extend(
                    [{"MetricName": "RecordsProcessed", "Value": 1, "Unit": "Count"}, {"MetricName": "DuplicatesSkipped", "Value": 1, "Unit": "Count"}]
                )
                continue

            claimed_observation_id = payload["observation_id"]

            if is_load_test:
                write_load_test_result(payload)
            elif not write_latest_vitals(payload):
                complete_observation_claim(claimed_observation_id, claim_token)
                metrics_by_namespace.setdefault(metric_namespace, []).extend(
                    [{"MetricName": "RecordsProcessed", "Value": 1, "Unit": "Count"}, {"MetricName": "StaleRecordsSkipped", "Value": 1, "Unit": "Count"}]
                )
                continue

            deliveries, delivery_failures, active_connections = push_vitals(payload)

            metric_data = build_metric_data(payload, deliveries, delivery_failures, active_connections)
            complete_observation_claim(claimed_observation_id, claim_token)

            metrics_by_namespace.setdefault(metric_namespace, []).extend(metric_data)

        except PermanentRecordError as error:
            print(f"Rejected permanent Kinesis record {sequence_number}: {error}")
            metrics_by_namespace.setdefault(METRIC_NAMESPACE, []).append({"MetricName": "PermanentRecordsRejected", "Value": 1, "Unit": "Count"})
        except Exception as error:
            print(f"Failed Kinesis record {sequence_number}: {error}")

            if claimed_observation_id and claim_token:
                try:
                    release_observation_claim(claimed_observation_id, claim_token)
                except Exception as release_error:
                    print(f"Failed to release idempotency claim for {claimed_observation_id}: {release_error}")

            batch_item_failures.append({"itemIdentifier": sequence_number})

    for namespace, metric_data in metrics_by_namespace.items():
        try:
            emit_metrics(metric_data, namespace=namespace)
        except Exception as error:
            print(f"Failed to emit {namespace} metrics: {error}")

    return {"batchItemFailures": batch_item_failures}
