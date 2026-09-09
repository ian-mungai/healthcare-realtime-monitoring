import json
from unittest.mock import Mock

import pytest

from services.fhir_webhook.app import config


@pytest.fixture(autouse=True)
def clear_secret_cache():
    config._get_webhook_secret.cache_clear()
    yield
    config._get_webhook_secret.cache_clear()


@pytest.mark.parametrize("ttl", ["0", "-1", "invalid"])
def test_invalid_cache_ttl_fails_closed(monkeypatch, ttl):
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_ID", "test-secret")
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_CACHE_TTL_SECONDS", ttl)
    with pytest.raises(RuntimeError, match="FHIR_WEBHOOK_SECRET_CACHE_TTL_SECONDS"):
        config.get_webhook_secret()


def test_refresh_failure_does_not_return_expired_secret(monkeypatch):
    client = Mock()
    client.get_secret_value.side_effect = [{"SecretString": json.dumps({"FHIR_WEBHOOK_SECRET": "old"})}, RuntimeError("unavailable")]
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_ID", "test-secret")
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_CACHE_TTL_SECONDS", "60")
    monkeypatch.setattr(config.boto3, "client", lambda _: client)
    monkeypatch.setattr(config.time, "time", lambda: 120)
    assert config.get_webhook_secret() == "old"
    monkeypatch.setattr(config.time, "time", lambda: 180)
    with pytest.raises(RuntimeError, match="unavailable"):
        config.get_webhook_secret()


def test_get_webhook_secret_reads_named_json_key(monkeypatch):
    class Client:
        def get_secret_value(self, **_):
            return {"SecretString": json.dumps({"FHIR_WEBHOOK_SECRET": "expected-secret"})}

    client = Client()
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_ID", "healthcare-realtime/fhir-webhook")
    monkeypatch.setattr(config.boto3, "client", lambda _: client)
    config._get_webhook_secret.cache_clear()

    assert config.get_webhook_secret() == "expected-secret"


def test_get_webhook_secret_requires_configured_identifier(monkeypatch):
    monkeypatch.delenv("FHIR_WEBHOOK_SECRET_ID", raising=False)
    config._get_webhook_secret.cache_clear()

    with pytest.raises(RuntimeError, match="FHIR_WEBHOOK_SECRET_ID"):
        config.get_webhook_secret()


def test_get_webhook_secret_refreshes_after_ttl_window(monkeypatch):
    class Client:
        calls = 0

        def get_secret_value(self, **_):
            self.calls += 1
            return {"SecretString": json.dumps({"FHIR_WEBHOOK_SECRET": f"secret-{self.calls}"})}

    client = Client()
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_ID", "healthcare-realtime/fhir-webhook")
    monkeypatch.setenv("FHIR_WEBHOOK_SECRET_CACHE_TTL_SECONDS", "60")
    monkeypatch.setattr(config.boto3, "client", lambda _: client)
    config._get_webhook_secret.cache_clear()

    monkeypatch.setattr(config.time, "time", lambda: 120)
    assert config.get_webhook_secret() == "secret-1"
    assert config.get_webhook_secret() == "secret-1"

    monkeypatch.setattr(config.time, "time", lambda: 180)
    assert config.get_webhook_secret() == "secret-2"
