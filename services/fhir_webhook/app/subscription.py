from services.fhir_webhook.app.security import WEBHOOK_SECRET_HEADER


def build_observation_subscription(webhook_url: str, webhook_secret: str) -> dict:
    if not webhook_url.startswith("https://"):
        raise ValueError("Webhook URL must use HTTPS")

    if not webhook_secret:
        raise ValueError("Webhook secret is required")

    return {
        "resourceType": "Subscription",
        "status": "requested",
        "reason": "Stream newly created vital sign Observations to the realtime monitoring pipeline",
        "criteria": "Observation?status=final",
        "channel": {"type": "rest-hook", "endpoint": webhook_url, "payload": "application/fhir+json", "header": [f"{WEBHOOK_SECRET_HEADER}: {webhook_secret}"]},
    }
