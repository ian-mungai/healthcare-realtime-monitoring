"""The ingestion workflow's webhook health checks (airflow/dags/lib/ingestion_health.py).

Each check raises when ingestion is unhealthy, so its task fails and the workflow's task-failure alarm fires.

Failure modes (written before the code):

1. The webhook answers with an error status, or 200 with a body that is not healthy, and the check passes.
2. A network error or timeout is caught and the check passes.
3. HAPI holds the subscription but it is not active, or it delivers to another endpoint or for other resources, and
   the check passes.
4. The webhook Lambda had errors in the last 30 minutes and the check passes; or an idle period without deliveries,
   which is normal when no simulator runs, fails it.
5. The webhook's API ID exists only after the application apply, so a URL fixed when the workflow is generated points
   nowhere: the checks find the API by its Terraform name at run time; its name, paths and Lambda name match Terraform.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from testkit import expect

ROOT = Path(__file__).resolve().parents[2]
API_ENDPOINT = "https://abc123.execute-api.example-region-1.amazonaws.com"
WEBHOOK_URL = f"{API_ENDPOINT}/development/webhooks/fhir"
FHIR_BASE_URL = "http://hapi.example.com/fhir"


def apis() -> MagicMock:
    client = MagicMock()
    client.get_apis.side_effect = [
        {"Items": [{"Name": "another-api", "ApiEndpoint": "https://other.example.com"}], "NextToken": "page-2"},
        {"Items": [{"Name": "healthcare-realtime-vitals-api", "ApiEndpoint": API_ENDPOINT}]},
    ]
    return client


def health_module():
    from airflow.dags.lib import ingestion_health

    return ingestion_health


def opener(status: int, body: Any):
    def get(url, headers, timeout):
        response = MagicMock(status_code=status)
        response.json.return_value = body
        return response

    return get


def subscription(status: str = "active", endpoint: str = WEBHOOK_URL, criteria: str = "Observation?status=final") -> dict:
    return {"resource": {"resourceType": "Subscription", "status": status, "criteria": criteria, "channel": {"type": "rest-hook", "endpoint": endpoint}}}


def test_the_webhook_must_answer_healthy() -> None:
    health = health_module()
    seen = []

    def healthy(url, headers, timeout):
        seen.append(url)
        return opener(200, {"status": "healthy"})(url, headers, timeout)

    expect.equal(health.check_webhook_health("development", "example-region-1", get=healthy, apis=apis())["status"], "healthy")
    expect.equal(seen, [f"{API_ENDPOINT}/development/health"])
    with pytest.raises(health.IngestionHealthError, match="503"):
        health.check_webhook_health("development", "example-region-1", get=opener(503, {}), apis=apis())
    with pytest.raises(health.IngestionHealthError, match="degraded"):
        health.check_webhook_health("development", "example-region-1", get=opener(200, {"status": "degraded"}), apis=apis())


def test_a_network_error_fails_the_check() -> None:
    health = health_module()

    def unreachable(url, headers, timeout):
        raise requests.ConnectionError("timed out")

    with pytest.raises(health.IngestionHealthError, match="timed out"):
        health.check_webhook_health("development", "example-region-1", get=unreachable, apis=apis())


def test_hapi_must_hold_an_active_observation_subscription_to_the_webhook() -> None:
    health = health_module()
    bundle = {"resourceType": "Bundle", "entry": [subscription(endpoint="https://other.example.com/hook"), subscription()]}

    expect.equal(health.check_subscription_active(FHIR_BASE_URL, "development", "example-region-1", get=opener(200, bundle), apis=apis())["status"], "active")
    for wrong in (subscription(status="error"), subscription(endpoint="https://other.example.com/hook"), subscription(criteria="Patient?")):
        with pytest.raises(health.IngestionHealthError, match="no active"):
            bundle = {"resourceType": "Bundle", "entry": [wrong]}
            health.check_subscription_active(FHIR_BASE_URL, "development", "example-region-1", get=opener(200, bundle), apis=apis())


def test_webhook_errors_fail_and_an_idle_period_passes() -> None:
    health = health_module()

    def cloudwatch(errors: float, invocations: float) -> MagicMock:
        client = MagicMock()
        sums = {"Errors": errors, "Invocations": invocations}
        client.get_metric_statistics.side_effect = lambda **kwargs: {"Datapoints": [{"Sum": sums[kwargs["MetricName"]]}] if sums[kwargs["MetricName"]] else []}
        return client

    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    idle = health.check_recent_deliveries("example-region-1", client=cloudwatch(0, 0), now=now)
    expect.equal((idle["errors"], idle["invocations"]), (0, 0))
    with pytest.raises(health.IngestionHealthError, match="3 errors"):
        health.check_recent_deliveries("example-region-1", client=cloudwatch(3, 40), now=now)


def test_a_missing_api_fails_the_check() -> None:
    health = health_module()
    client = MagicMock()
    client.get_apis.return_value = {"Items": []}

    with pytest.raises(health.IngestionHealthError, match="healthcare-realtime-vitals-api"):
        health.check_webhook_health("development", "example-region-1", get=opener(200, {"status": "healthy"}), apis=client)


def test_the_names_and_paths_match_terraform() -> None:
    health = health_module()
    api = (ROOT / "infra" / "modules" / "vitals_api" / "main.tf").read_text(encoding="utf-8")
    webhook_outputs = (ROOT / "infra" / "modules" / "fhir_webhook" / "outputs.tf").read_text(encoding="utf-8")
    webhook = (ROOT / "infra" / "modules" / "fhir_webhook" / "main.tf").read_text(encoding="utf-8")

    expect.is_in(f'name          = "{health.VITALS_API_NAME}"', api)
    expect.is_in(f'"${{var.api_endpoint}}{health.WEBHOOK_PATH}"', webhook_outputs)
    expect.is_in(f'"${{var.api_endpoint}}{health.HEALTH_PATH}"', webhook_outputs)
    expect.is_in(f'function_name = "{health.WEBHOOK_LAMBDA}"', webhook)
