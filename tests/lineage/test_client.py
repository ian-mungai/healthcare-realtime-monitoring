from unittest.mock import Mock

import pytest

from lineage.openlineage import client


def test_runtime_client_uses_s3_without_collector(monkeypatch) -> None:
    expected = Mock()
    build_s3 = Mock(return_value=expected)
    monkeypatch.delenv("OPENLINEAGE_URL", raising=False)
    monkeypatch.setattr(client, "build_s3_openlineage_client", build_s3)

    assert client.build_runtime_openlineage_client("s3://project-bucket/lineage/event") is expected
    build_s3.assert_called_once_with("s3://project-bucket/lineage/event")


def test_runtime_client_uses_shared_http_collector(monkeypatch) -> None:
    transport = Mock()
    http_transport = Mock(return_value=transport)
    openlineage_client = Mock()
    monkeypatch.setenv("OPENLINEAGE_URL", "https://lineage.example.com/")
    monkeypatch.setenv("OPENLINEAGE_ENDPOINT", "/api/v1/lineage/")
    monkeypatch.setattr(client, "HttpTransport", http_transport)
    monkeypatch.setattr(client, "OpenLineageClient", openlineage_client)

    client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    config = http_transport.call_args.args[0]
    assert config.url == "https://lineage.example.com"
    assert config.endpoint == "api/v1/lineage"
    assert config.session is None
    openlineage_client.assert_called_once_with(transport=transport)


def test_runtime_client_sigv4_signs_managed_collector(monkeypatch) -> None:
    transport = Mock()
    http_transport = Mock(return_value=transport)
    openlineage_client = Mock()
    session = Mock()
    build_sigv4_session = Mock(return_value=session)
    monkeypatch.setenv("OPENLINEAGE_URL", "https://collector-id.execute-api.us-east-1.amazonaws.com/development")
    monkeypatch.setattr(client, "HttpTransport", http_transport)
    monkeypatch.setattr(client, "OpenLineageClient", openlineage_client)
    monkeypatch.setattr(client, "build_sigv4_session", build_sigv4_session)

    client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    config = http_transport.call_args.args[0]
    assert config.session is session
    build_sigv4_session.assert_called_once_with("us-east-1")
    openlineage_client.assert_called_once_with(transport=transport)


def test_execute_api_region_rejects_non_aws_hosts() -> None:
    assert client.execute_api_region("collector-id.execute-api.us-east-1.amazonaws.com") == "us-east-1"
    assert client.execute_api_region("lineage.example.com") is None
    assert client.execute_api_region(None) is None


def test_runtime_client_rejects_invalid_collector_configuration(monkeypatch) -> None:
    monkeypatch.setenv("OPENLINEAGE_URL", "lineage.example.com")
    with pytest.raises(ValueError, match="absolute HTTP"):
        client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    monkeypatch.setenv("OPENLINEAGE_URL", "https://lineage.example.com")
    monkeypatch.setenv("OPENLINEAGE_ENDPOINT", "/")
    with pytest.raises(ValueError, match="must not be empty"):
        client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")
