"""GET /patients/{patient_id}/early-warning: NEWS2 from the live cache and the published model's real-time score.

NEWS2 comes from the patient's latest cached vitals. The model score is for the patient's current encounter: once its
15-minute feature window has closed (plus GRACE for late readings), the readings the stream processor kept in the
feature-window table are scored with the approved model's published parameters, and the score is stored once per
model version beside them, so every later request returns the same score. Before that the response says when the
window closes. Failure modes: tests/early_warning/test_handler.py.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from services.early_warning import scoring
    from services.feature_window import SCORE_PREFIX, TTL_SECONDS, score_key, time_key
    from services.realtime_authorization import is_patient_authorized
else:
    try:
        from services.early_warning import scoring
        from services.feature_window import SCORE_PREFIX, TTL_SECONDS, score_key, time_key
        from services.realtime_authorization import is_patient_authorized
    except ModuleNotFoundError:
        import scoring
        from authorization import is_patient_authorized
        from feature_window import SCORE_PREFIX, TTL_SECONDS, score_key, time_key

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
# Readings can reach the processor after their event time; the window is scored this long after it closes.
GRACE = timedelta(seconds=60)
MODEL_VERSION = os.getenv("ML_APPROVED_MODEL_VERSION", "")
MODEL_BUCKET = os.getenv("DATA_BUCKET_NAME", "")
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
latest_vitals_table = dynamodb.Table(os.environ["LATEST_VITALS_TABLE"])
feature_window_table = dynamodb.Table(os.environ["FEATURE_WINDOW_TABLE"])
s3 = boto3.client("s3", region_name=AWS_REGION)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def build_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body, cls=DecimalEncoder)}


def now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=4)
def load_parameters(version: str) -> dict[str, Any] | None:
    """The approved model's scoring parameters, or None when they are missing or fail their published checksum."""
    try:
        response = s3.get_object(Bucket=MODEL_BUCKET, Key=f"ml/model_artifacts/{version}/scoring_parameters.json")
    except ClientError:
        return None
    body = response["Body"].read()
    if hashlib.sha256(body).hexdigest() != response.get("Metadata", {}).get("sha256"):
        return None
    parameters = json.loads(body)
    return parameters if parameters.get("model_version") == version else None


def _plain(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def _query_all(**kwargs: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        page = feature_window_table.query(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _score_body(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("model_version", "probability", "window_start", "window_cutoff", "readings", "scored_at")
    return {"status": "scored", **{key: _plain(item[key]) for key in keys}}


def model_score(encounter_id: str | None) -> dict[str, Any]:
    """The encounter's score for the approved model, computed and stored once its window has closed."""
    if not encounter_id:
        return {"status": "no_encounter"}
    if not MODEL_VERSION:
        return {"status": "no_approved_model"}
    key = {"encounter_id": encounter_id, "reading": score_key(MODEL_VERSION)}
    stored = feature_window_table.get_item(Key=key, ConsistentRead=True).get("Item")
    if stored:
        return _score_body(stored)
    first = feature_window_table.query(
        KeyConditionExpression="encounter_id = :encounter AND reading < :before",
        ExpressionAttributeValues={":encounter": encounter_id, ":before": SCORE_PREFIX},
        Limit=1,
        ConsistentRead=True,
    ).get("Items", [])
    if not first:
        return {"status": "no_readings"}
    start = scoring.parse_time(str(first[0]["event_timestamp"]))
    cutoff = start + scoring.WINDOW
    if now() < cutoff + GRACE:
        return {"status": "window_open", "window_closes_at": iso(cutoff)}
    parameters = load_parameters(MODEL_VERSION)
    if parameters is None:
        return {"status": "model_unavailable", "model_version": MODEL_VERSION}
    # A reading at the cutoff sorts after the cutoff's time key, so BETWEEN leaves it out, as dbt does.
    readings = _query_all(
        KeyConditionExpression="encounter_id = :encounter AND reading BETWEEN :low AND :high",
        ExpressionAttributeValues={":encounter": encounter_id, ":low": time_key(start), ":high": time_key(cutoff)},
        ConsistentRead=True,
    )
    window = scoring.window_features([{name: _plain(value) for name, value in item.items()} for item in readings])
    item = {
        **key,
        "model_version": MODEL_VERSION,
        "probability": Decimal(repr(scoring.probability(window.features, parameters))),
        "window_start": iso(window.start),
        "window_cutoff": iso(window.cutoff),
        "readings": window.readings,
        "scored_at": iso(now()),
        "expires_at": int(now().timestamp()) + TTL_SECONDS,
    }
    try:
        feature_window_table.put_item(Item=item, ConditionExpression="attribute_not_exists(reading)")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        item = feature_window_table.get_item(Key=key, ConsistentRead=True)["Item"]
    return _score_body(item)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    patient_id = (event.get("pathParameters") or {}).get("patient_id")
    if not patient_id:
        return build_response(400, {"message": "patient_id is required"})
    if not is_patient_authorized(event, patient_id):
        return build_response(403, {"message": "Access to this patient is not authorized"})
    latest = latest_vitals_table.get_item(Key={"patient_id": patient_id}, ConsistentRead=True).get("Item")
    if not latest:
        return build_response(404, {"message": f"No latest vitals found for patient {patient_id}"})
    vitals = {name: _plain(value) for name, value in latest.items() if not name.startswith("_")}
    return build_response(
        200,
        {
            "patient_id": patient_id,
            "encounter_id": latest.get("encounter_id"),
            "news2": scoring.news2_summary(vitals),
            "model": model_score(latest.get("encounter_id")),
        },
    )
