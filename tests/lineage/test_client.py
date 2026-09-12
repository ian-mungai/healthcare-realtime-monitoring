from unittest.mock import Mock
from urllib.parse import urljoin

import pytest

from lineage.openlineage import client


def test_runtime_client_uses_s3_without_collector(monkeypatch, capsys) -> None:
    expected = Mock()
    build_s3 = Mock(return_value=expected)
    monkeypatch.delenv("OPENLINEAGE_URL", raising=False)
    monkeypatch.setattr(client, "build_s3_openlineage_client", build_s3)

    assert client.build_runtime_openlineage_client("s3://project-bucket/lineage/event") is expected
    build_s3.assert_called_once_with("s3://project-bucket/lineage/event")
    assert "OpenLineage transport selected: S3" in capsys.readouterr().out


def test_runtime_client_uses_shared_http_collector(monkeypatch, capsys) -> None:
    transport = Mock()
    http_transport = Mock(return_value=transport)
    openlineage_client = Mock()
    session = Mock()
    monkeypatch.setenv("OPENLINEAGE_URL", "https://lineage.example.com/")
    monkeypatch.setenv("OPENLINEAGE_ENDPOINT", "/api/v1/lineage/")
    monkeypatch.setenv("OPENLINEAGE_AWS_REGION", "us-east-1")
    monkeypatch.setattr(client, "HttpTransport", http_transport)
    monkeypatch.setattr(client, "OpenLineageClient", openlineage_client)
    monkeypatch.setattr(client, "build_sigv4_session", Mock(return_value=session))

    client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    config = http_transport.call_args.args[0]
    assert config.url == "https://lineage.example.com/"
    assert config.endpoint == "api/v1/lineage"
    assert config.session is session
    openlineage_client.assert_called_once_with(transport=transport)
    assert "OpenLineage transport selected: SigV4 HTTP in us-east-1" in capsys.readouterr().out


def test_runtime_client_sigv4_signs_managed_collector(monkeypatch) -> None:
    transport = Mock()
    http_transport = Mock(return_value=transport)
    openlineage_client = Mock()
    session = Mock()
    build_sigv4_session = Mock(return_value=session)
    monkeypatch.setenv("OPENLINEAGE_URL", "https://collector-id.execute-api.us-east-1.amazonaws.com/development")
    monkeypatch.setenv("OPENLINEAGE_AWS_REGION", "us-east-1")
    monkeypatch.setattr(client, "HttpTransport", http_transport)
    monkeypatch.setattr(client, "OpenLineageClient", openlineage_client)
    monkeypatch.setattr(client, "build_sigv4_session", build_sigv4_session)

    client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    config = http_transport.call_args.args[0]
    assert config.session is session
    assert urljoin(config.url, config.endpoint) == ("https://collector-id.execute-api.us-east-1.amazonaws.com/development/api/v1/lineage")
    build_sigv4_session.assert_called_once_with("us-east-1")
    openlineage_client.assert_called_once_with(transport=transport)


def test_runtime_client_allows_unsigned_local_collector(monkeypatch) -> None:
    http_transport = Mock(return_value=Mock())
    monkeypatch.setenv("OPENLINEAGE_URL", "http://localhost:5000")
    monkeypatch.delenv("OPENLINEAGE_AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr(client, "HttpTransport", http_transport)

    client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    assert http_transport.call_args.args[0].session is None


def test_runtime_client_rejects_unsigned_remote_collector(monkeypatch) -> None:
    monkeypatch.setenv("OPENLINEAGE_URL", "https://lineage.example.com")
    monkeypatch.delenv("OPENLINEAGE_AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    with pytest.raises(ValueError, match="required to sign"):
        client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")


def test_runtime_client_rejects_invalid_collector_configuration(monkeypatch) -> None:
    monkeypatch.setenv("OPENLINEAGE_URL", "lineage.example.com")
    with pytest.raises(ValueError, match="absolute HTTP"):
        client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    monkeypatch.setenv("OPENLINEAGE_URL", "https://lineage.example.com")
    monkeypatch.setenv("OPENLINEAGE_ENDPOINT", "/")
    with pytest.raises(ValueError, match="must not be empty"):
        client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")


def test_runtime_lineage_emission_does_not_fail_workload(monkeypatch, capsys) -> None:
    runtime_client = Mock()
    runtime_client.emit.side_effect = RuntimeError("collector unavailable")
    monkeypatch.setattr(client, "build_runtime_openlineage_client", Mock(return_value=runtime_client))

    emitted = client.emit_runtime_lineage_event("s3://project-bucket/lineage/event", lambda: {"eventType": "START"}, "athena", "START")

    assert emitted is False
    assert "OpenLineage athena START emission failed: RuntimeError: collector unavailable" in capsys.readouterr().out
