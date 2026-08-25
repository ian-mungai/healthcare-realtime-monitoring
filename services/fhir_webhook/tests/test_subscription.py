import pytest

from services.fhir_webhook.app.subscription import build_observation_subscription


def test_build_observation_subscription():
    subscription = build_observation_subscription(webhook_url="https://example.com/webhooks/fhir", webhook_secret="secret_123")

    assert subscription["resourceType"] == "Subscription"
    assert subscription["status"] == "requested"
    assert subscription["criteria"] == "Observation?status=final"
    assert subscription["channel"]["type"] == "rest-hook"
    assert subscription["channel"]["endpoint"] == "https://example.com/webhooks/fhir"
    assert subscription["channel"]["header"] == ["X-Webhook-Secret: secret_123"]


def test_subscription_requires_https():
    with pytest.raises(ValueError, match="HTTPS"):
        build_observation_subscription(webhook_url="http://example.com/webhooks/fhir", webhook_secret="secret_123")
