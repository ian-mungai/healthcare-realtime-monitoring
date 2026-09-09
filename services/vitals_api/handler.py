import json
import os
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from services.realtime_authorization import is_patient_authorized
else:
    try:
        from services.realtime_authorization import is_patient_authorized
    except ModuleNotFoundError:
        from authorization import is_patient_authorized

LATEST_VITALS_TABLE = os.getenv("LATEST_VITALS_TABLE", "healthcare-realtime-latest-vitals")
AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
VITAL_FIELDS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "diastolic_bp")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
latest_vitals_table = dynamodb.Table(LATEST_VITALS_TABLE)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)

        return super().default(obj)


def build_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body, cls=DecimalEncoder)}


def get_latest_vitals_table() -> Any:
    return latest_vitals_table


def latest_measurement_timestamp(item: dict[str, Any]) -> str | None:
    timestamp_values = [value for key, value in item.items() if key.endswith("_event_timestamp") and not key.startswith("_")]
    if timestamp_values:
        return max(timestamp_values)
    return item.get("event_timestamp")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    path_parameters = event.get("pathParameters") or {}
    patient_id = path_parameters.get("patient_id")

    if not patient_id:
        return build_response(400, {"message": "patient_id is required"})

    if not is_patient_authorized(event, patient_id):
        return build_response(403, {"message": "Access to this patient is not authorized"})

    result = get_latest_vitals_table().get_item(Key={"patient_id": patient_id}, ConsistentRead=True)

    item = result.get("Item")

    if not item:
        return build_response(404, {"message": f"No latest vitals found for patient {patient_id}"})

    public_item = {key: value for key, value in item.items() if not key.startswith("_")}
    legacy_timestamp = public_item.get("event_timestamp")
    if legacy_timestamp:
        for field in VITAL_FIELDS:
            if public_item.get(field) is not None:
                public_item.setdefault(f"{field}_event_timestamp", legacy_timestamp)
    event_timestamp = latest_measurement_timestamp(public_item)
    if event_timestamp:
        public_item["event_timestamp"] = event_timestamp
    return build_response(200, public_item)
