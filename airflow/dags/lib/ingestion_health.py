"""Webhook health checks for the ingestion workflow (airflow/dags/healthcare_realtime_ingestion.py).

Each check returns what it saw or raises IngestionHealthError, which fails its task so the workflow's task-failure
alarm fires. The webhook's API is created in the same apply as this workflow, so its URL is not known when the
workflow is generated: the checks find the API by its Terraform name at run time. They use requests and boto3, which
the MWAA Serverless runtime provides. Failure modes: tests/ingestion/test_ingestion_health.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import requests

TIMEOUT_SECONDS = 10
# The window the delivery check reads, the same as the workflow's schedule.
DELIVERY_WINDOW = timedelta(minutes=30)
# The subscription services/fhir_webhook/app/subscription.py registers.
SUBSCRIPTION_CRITERIA = "Observation?status=final"
# Fixed in Terraform: infra/modules/vitals_api/main.tf and infra/modules/fhir_webhook (outputs.tf and main.tf).
VITALS_API_NAME = "healthcare-realtime-vitals-api"
WEBHOOK_PATH = "/webhooks/fhir"
HEALTH_PATH = "/health"
WEBHOOK_LAMBDA = "healthcare_realtime_fhir_webhook"

Getter = Callable[..., Any]


class IngestionHealthError(RuntimeError):
    """Ingestion is not healthy; the message names what failed."""


def _get_json(url: str, get: Getter, accept: str = "application/json") -> Any:
    try:
        response = get(url, headers={"Accept": accept}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise IngestionHealthError(f"{url} could not be read: {error}") from error
    if response.status_code != 200:
        raise IngestionHealthError(f"{url} answered HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as error:
        raise IngestionHealthError(f"{url} did not answer JSON") from error


def resolve_api_endpoint(stage: str, aws_region: str, apis: Any = None) -> str:
    """The vitals API's stage URL, which the webhook routes share, found by the API's name."""
    client = apis or boto3.client("apigatewayv2", region_name=aws_region)
    arguments: dict[str, Any] = {}
    while True:
        page = client.get_apis(**arguments)
        for api in page.get("Items", []):
            if api.get("Name") == VITALS_API_NAME:
                return f"{api['ApiEndpoint'].rstrip('/')}/{stage}"
        if not page.get("NextToken"):
            raise IngestionHealthError(f"no API Gateway API named {VITALS_API_NAME} in {aws_region}")
        arguments = {"NextToken": page["NextToken"]}


def check_webhook_health(stage: str, aws_region: str, get: Getter = requests.get, apis: Any = None) -> dict[str, Any]:
    """The webhook's GET /health route answers 200 with status healthy."""
    body = _get_json(f"{resolve_api_endpoint(stage, aws_region, apis)}{HEALTH_PATH}", get)
    if not isinstance(body, dict) or body.get("status") != "healthy":
        raise IngestionHealthError(f"the webhook reported {body.get('status') if isinstance(body, dict) else body!r}, not healthy")
    return body


def check_subscription_active(fhir_base_url: str, stage: str, aws_region: str, get: Getter = requests.get, apis: Any = None) -> dict[str, Any]:
    """HAPI holds an active rest-hook subscription for final Observations that delivers to the webhook."""
    target = f"{resolve_api_endpoint(stage, aws_region, apis)}{WEBHOOK_PATH}"
    bundle = _get_json(f"{fhir_base_url.rstrip('/')}/Subscription?status=active&_count=100", get, "application/fhir+json")
    for entry in bundle.get("entry", []) if isinstance(bundle, dict) else []:
        resource = entry.get("resource", {})
        channel = resource.get("channel", {})
        if (
            resource.get("status") == "active"
            and resource.get("criteria") == SUBSCRIPTION_CRITERIA
            and channel.get("type") == "rest-hook"
            and str(channel.get("endpoint", "")).rstrip("/") == target
        ):
            return {"status": "active", "subscription_id": resource.get("id")}
    raise IngestionHealthError(f"HAPI has no active {SUBSCRIPTION_CRITERIA} rest-hook subscription to the webhook")


def check_recent_deliveries(aws_region: str, client: Any = None, now: datetime | None = None) -> dict[str, int]:
    """The webhook Lambda had no errors in the last DELIVERY_WINDOW; a window without deliveries passes."""
    cloudwatch = client or boto3.client("cloudwatch", region_name=aws_region)
    end = now or datetime.now(UTC)
    sums = {}
    for metric in ("Errors", "Invocations"):
        datapoints = cloudwatch.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName=metric,
            Dimensions=[{"Name": "FunctionName", "Value": WEBHOOK_LAMBDA}],
            StartTime=end - DELIVERY_WINDOW,
            EndTime=end,
            Period=int(DELIVERY_WINDOW.total_seconds()),
            Statistics=["Sum"],
        )["Datapoints"]
        sums[metric] = int(sum(point["Sum"] for point in datapoints))
    if sums["Errors"]:
        raise IngestionHealthError(f"the webhook Lambda had {sums['Errors']} errors in {sums['Invocations']} invocations over the last 30 minutes")
    return {"errors": sums["Errors"], "invocations": sums["Invocations"]}
