import json
import os
from decimal import Decimal
from typing import Any

import boto3

LATEST_VITALS_TABLE = os.getenv("LATEST_VITALS_TABLE", "healthcare-realtime-latest-vitals")


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)

        return super().default(obj)


def build_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def get_latest_vitals_table() -> Any:
    return boto3.resource("dynamodb").Table(LATEST_VITALS_TABLE)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    path_parameters = event.get("pathParameters") or {}
    patient_id = path_parameters.get("patient_id")

    if not patient_id:
        return build_response(400, {"message": "patient_id is required"})

    result = get_latest_vitals_table().get_item(Key={"patient_id": patient_id}, ConsistentRead=True)

    item = result.get("Item")

    if not item:
        return build_response(404, {"message": f"No latest vitals found for patient {patient_id}"})

    return build_response(200, item)
