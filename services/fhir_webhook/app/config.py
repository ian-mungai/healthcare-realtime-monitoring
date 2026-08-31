import os


def get_webhook_secret() -> str:
    secret = os.getenv("FHIR_WEBHOOK_SECRET")

    if not secret:
        raise RuntimeError("FHIR_WEBHOOK_SECRET is not configured")

    return secret
