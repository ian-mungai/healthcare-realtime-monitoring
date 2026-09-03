import json
import os
from functools import lru_cache

import boto3

SECRET_ID_ENVIRONMENT_VARIABLE = "FHIR_WEBHOOK_SECRET_ID"
SECRET_KEY = "FHIR_WEBHOOK_SECRET"


@lru_cache
def get_webhook_secret() -> str:
    secret_id = os.getenv(SECRET_ID_ENVIRONMENT_VARIABLE)

    if not secret_id:
        raise RuntimeError(f"{SECRET_ID_ENVIRONMENT_VARIABLE} is not configured")

    secret_string = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]

    try:
        secret = json.loads(secret_string)[SECRET_KEY]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Secrets Manager secret {secret_id!r} must contain {SECRET_KEY!r}") from error

    if not isinstance(secret, str) or not secret:
        raise RuntimeError(f"Secrets Manager secret {secret_id!r} must contain a non-empty {SECRET_KEY!r}")

    return secret
