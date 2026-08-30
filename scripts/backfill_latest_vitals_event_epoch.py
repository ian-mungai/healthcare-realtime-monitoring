import argparse
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

DEFAULT_TABLE_NAME = "healthcare-realtime-latest-vitals"
dynamodb = boto3.resource("dynamodb")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill DynamoDB latest-vitals event ordering metadata.")
    parser.add_argument("--table-name", default=DEFAULT_TABLE_NAME)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def event_timestamp_epoch_ms(event_timestamp: str) -> int:
    event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))

    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    return int(event_time.timestamp() * 1000)


def scan_items(table: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    scan_parameters: dict[str, Any] = {
        "ProjectionExpression": "patient_id, event_timestamp, #legacy_timestamp, #event_epoch",
        "ExpressionAttributeNames": {"#legacy_timestamp": "timestamp", "#event_epoch": "_event_timestamp_epoch_ms"},
    }

    while True:
        response = table.scan(**scan_parameters)

        items.extend(response.get("Items", []))

        last_evaluated_key = response.get("LastEvaluatedKey")

        if not last_evaluated_key:
            break

        scan_parameters["ExclusiveStartKey"] = last_evaluated_key

    return items


def resolve_event_timestamp(item: dict[str, Any]) -> str | None:
    event_timestamp = item.get("event_timestamp")

    if event_timestamp:
        return str(event_timestamp)

    legacy_timestamp = item.get("timestamp")

    if legacy_timestamp:
        return str(legacy_timestamp)

    return None


def backfill_item(table: Any, patient_id: str, event_timestamp: str, epoch_ms: int, migrate_legacy_timestamp: bool) -> bool:
    expression_attribute_names = {"#event_epoch": "_event_timestamp_epoch_ms"}
    expression_attribute_values = {":event_epoch": epoch_ms}
    update_expression = "SET #event_epoch = :event_epoch"

    if migrate_legacy_timestamp:
        expression_attribute_names["#event_timestamp"] = "event_timestamp"
        expression_attribute_values[":event_timestamp"] = event_timestamp
        update_expression += ", #event_timestamp = :event_timestamp"

    try:
        table.update_item(
            Key={"patient_id": patient_id},
            UpdateExpression=update_expression,
            ConditionExpression="attribute_not_exists(#event_epoch)",
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
        )

    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False

        raise

    return True


def main() -> None:
    args = parse_args()
    table = dynamodb.Table(args.table_name)

    items = scan_items(table)

    existing_count = 0
    candidate_count = 0
    legacy_count = 0
    invalid_count = 0
    updated_count = 0

    for item in items:
        patient_id = item.get("patient_id")

        if "_event_timestamp_epoch_ms" in item:
            existing_count += 1
            continue

        event_timestamp = resolve_event_timestamp(item)

        if not patient_id or not event_timestamp:
            invalid_count += 1
            print(f"SKIP missing patient_id or timestamp: {item}")
            continue

        migrate_legacy_timestamp = not item.get("event_timestamp") and bool(item.get("timestamp"))

        try:
            epoch_ms = event_timestamp_epoch_ms(event_timestamp)

        except (TypeError, ValueError) as error:
            invalid_count += 1
            print(f"SKIP invalid timestamp for patient {patient_id}: {event_timestamp!r} ({error})")
            continue

        candidate_count += 1

        if migrate_legacy_timestamp:
            legacy_count += 1

        if not args.apply:
            timestamp_source = "timestamp" if migrate_legacy_timestamp else "event_timestamp"
            print(f"DRY RUN patient={patient_id} timestamp={event_timestamp} source={timestamp_source} epoch_ms={epoch_ms}")
            continue

        if backfill_item(table, str(patient_id), event_timestamp, epoch_ms, migrate_legacy_timestamp):
            updated_count += 1
            print(f"UPDATED patient={patient_id} epoch_ms={epoch_ms} migrated_legacy_timestamp={migrate_legacy_timestamp}")
        else:
            print(f"SKIP patient={patient_id} was updated concurrently")

    print(
        f"Summary scanned={len(items)} existing={existing_count} candidates={candidate_count} legacy={legacy_count} "
        f"invalid={invalid_count} updated={updated_count} mode={'apply' if args.apply else 'dry-run'}"
    )


if __name__ == "__main__":
    main()
