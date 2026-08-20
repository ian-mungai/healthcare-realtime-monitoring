import os

DEFAULT_WEBHOOK_HOST = "127.0.0.1"
DEFAULT_WEBHOOK_PORT = 8002


def get_webhook_secret() -> str:
    secret = os.getenv("FHIR_WEBHOOK_SECRET")

    if not secret:
        raise RuntimeError("FHIR_WEBHOOK_SECRET is not configured")

    return secret