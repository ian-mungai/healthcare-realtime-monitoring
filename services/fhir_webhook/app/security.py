import hmac

from services.fhir_webhook.app.config import get_webhook_secret

WEBHOOK_SECRET_HEADER = "X-Webhook-Secret"


def validate_webhook_secret(received_secret: str | None) -> bool:
    if received_secret is None:
        return False

    expected_secret = get_webhook_secret()

    return hmac.compare_digest(received_secret, expected_secret)
