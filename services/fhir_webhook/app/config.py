import json
import os
import time
from functools import lru_cache

import boto3

SECRET_ID_ENVIRONMENT_VARIABLE = "FHIR_WEBHOOK_SECRET_ID"
SECRET_KEY = "FHIR_WEBHOOK_SECRET"
SECRET_CACHE_TTL_ENVIRONMENT_VARIABLE = "FHIR_WEBHOOK_SECRET_CACHE_TTL_SECONDS"


@lru_cache(maxsize=2)
def _get_webhook_secret(secret_id: str, cache_window: int) -> str:
    del cache_window
    secret_string = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]

    try:
        secret = json.loads(secret_string)[SECRET_KEY]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Secrets Manager secret {secret_id!r} must contain {SECRET_KEY!r}") from error

    if not isinstance(secret, str) or not secret:
        raise RuntimeError(f"Secrets Manager secret {secret_id!r} must contain a non-empty {SECRET_KEY!r}")

    return secret


def get_webhook_secret() -> str:
    secret_id = os.getenv(SECRET_ID_ENVIRONMENT_VARIABLE)

    if not secret_id:
        raise RuntimeError(f"{SECRET_ID_ENVIRONMENT_VARIABLE} is not configured")

    try:
        cache_ttl_seconds = int(os.getenv(SECRET_CACHE_TTL_ENVIRONMENT_VARIABLE, "300"))
    except ValueError as error:
        raise RuntimeError(f"{SECRET_CACHE_TTL_ENVIRONMENT_VARIABLE} must be an integer") from error

    if cache_ttl_seconds <= 0:
        raise RuntimeError(f"{SECRET_CACHE_TTL_ENVIRONMENT_VARIABLE} must be greater than zero")

    return _get_webhook_secret(secret_id, int(time.time() // cache_ttl_seconds))
