import pytest

from services.fhir_webhook.app.subscription import build_observation_subscription
from testkit import expect

SAMPLE_CREDENTIAL = "secret_123"


def test_build_observation_subscription():
    subscription = build_observation_subscription(webhook_url="https://example.com/webhooks/fhir", webhook_secret=SAMPLE_CREDENTIAL)

    expect.equal(subscription["resourceType"], "Subscription")
    expect.equal(subscription["status"], "requested")
    expect.equal(subscription["criteria"], "Observation?status=final")
    expect.equal(subscription["channel"]["type"], "rest-hook")
    expect.equal(subscription["channel"]["endpoint"], "https://example.com/webhooks/fhir")
    expect.equal(subscription["channel"]["header"], ["X-Webhook-Secret: secret_123"])


def test_subscription_requires_https():
    with pytest.raises(ValueError, match="HTTPS"):
        build_observation_subscription(webhook_url="http://example.com/webhooks/fhir", webhook_secret=SAMPLE_CREDENTIAL)
