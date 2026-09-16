from unittest.mock import Mock
from urllib.parse import urljoin

import pytest
from botocore.credentials import Credentials
from requests import Response
from requests.exceptions import HTTPError

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
    sigv4_transport = Mock(return_value=transport)
    openlineage_client = Mock()
    monkeypatch.setenv("OPENLINEAGE_URL", "https://lineage.example.com/")
    monkeypatch.setenv("OPENLINEAGE_ENDPOINT", "/api/v1/lineage/")
    monkeypatch.setenv("OPENLINEAGE_AWS_REGION", "example-region-1")
    monkeypatch.setattr(client, "AwsSigV4HttpTransport", sigv4_transport)
    monkeypatch.setattr(client, "OpenLineageClient", openlineage_client)

    client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    sigv4_transport.assert_called_once_with("https://lineage.example.com/", "api/v1/lineage", "example-region-1")
    openlineage_client.assert_called_once_with(transport=transport)
    assert "OpenLineage transport selected: SigV4 HTTP in example-region-1" in capsys.readouterr().out


def test_runtime_client_sigv4_signs_managed_collector(monkeypatch) -> None:
    transport = Mock()
    sigv4_transport = Mock(return_value=transport)
    openlineage_client = Mock()
    monkeypatch.setenv("OPENLINEAGE_URL", "https://collector-id.execute-api.example-region-1.amazonaws.com/development")
    monkeypatch.setenv("OPENLINEAGE_AWS_REGION", "example-region-1")
    monkeypatch.setattr(client, "AwsSigV4HttpTransport", sigv4_transport)
    monkeypatch.setattr(client, "OpenLineageClient", openlineage_client)

    client.build_runtime_openlineage_client("s3://project-bucket/lineage/event")

    url, endpoint, region = sigv4_transport.call_args.args
    assert urljoin(url, endpoint) == "https://collector-id.execute-api.example-region-1.amazonaws.com/development/api/v1/lineage"
    assert region == "example-region-1"
    openlineage_client.assert_called_once_with(transport=transport)


def test_sigv4_transport_sends_the_signed_aws_request(monkeypatch) -> None:
    response = Mock(status_code=201)
    http_session = Mock()
    http_session.send.return_value = response
    boto_session = Mock()
    boto_session.get_credentials.return_value = Credentials("access-key", "secret-key", "session-token")
    monkeypatch.setattr(client, "URLLib3Session", Mock(return_value=http_session))
    monkeypatch.setattr(client.boto3, "Session", Mock(return_value=boto_session))
    monkeypatch.setattr(client.Serde, "to_json", Mock(return_value='{"eventType":"START"}'))

    transport = client.AwsSigV4HttpTransport(
        "https://collector-id.execute-api.example-region-1.amazonaws.com/development/", "api/v1/lineage", "example-region-1"
    )

    assert transport.emit(Mock()) is response
    request = http_session.send.call_args.args[0]
    assert request.url == "https://collector-id.execute-api.example-region-1.amazonaws.com/development/api/v1/lineage"
    assert request.body == b'{"eventType":"START"}'
    assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert request.headers["X-Amz-Security-Token"] == "session-token"


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


def test_runtime_lineage_emission_logs_http_error_response(monkeypatch, capsys) -> None:
    response = Response()
    response.status_code = 403
    response._content = b'{"message": "The security token is invalid"}'
    runtime_client = Mock()
    runtime_client.emit.side_effect = HTTPError(response=response)
    monkeypatch.setattr(client, "build_runtime_openlineage_client", Mock(return_value=runtime_client))

    emitted = client.emit_runtime_lineage_event("s3://project-bucket/lineage/event", lambda: {"eventType": "START"}, "glue", "START")

    assert emitted is False
    assert 'OpenLineage glue START emission failed: HTTPError: status=403; response={"message": "The security token is invalid"}' in capsys.readouterr().out
