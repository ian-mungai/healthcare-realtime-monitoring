import json

import pytest

from services.fhir_webhook.app import config


def test_get_webhook_secret_reads_named_json_key(monkeypatch):
    class Client:
        def get_secret_value(self, **_):
            return {"SecretString": json.dumps({"FHIR_WEBHOOK_SECRET": "expected-secret"})}

    client = Client()
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_ID", "healthcare-realtime/fhir-webhook")
    monkeypatch.setattr(config.boto3, "client", lambda _: client)
    config.get_webhook_secret.cache_clear()

    assert config.get_webhook_secret() == "expected-secret"


def test_get_webhook_secret_requires_configured_identifier(monkeypatch):
    monkeypatch.delenv("FHIR_WEBHOOK_SECRET_ID", raising=False)
    config.get_webhook_secret.cache_clear()

    with pytest.raises(RuntimeError, match="FHIR_WEBHOOK_SECRET_ID"):
        config.get_webhook_secret()
