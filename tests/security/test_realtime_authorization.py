import json

from services.realtime_authorization import get_principal_arn, is_patient_authorized, load_patient_access_policy


def test_authorizes_http_api_principal_for_matching_patient(monkeypatch) -> None:
    principal = "arn:aws:iam::111111111111:user/dashboard-test"
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", json.dumps({principal: ["patient-1000"]}))
    event = {"requestContext": {"authorizer": {"iam": {"userArn": principal}}}}

    assert get_principal_arn(event) == principal
    assert is_patient_authorized(event, "patient-1000") is True
    assert is_patient_authorized(event, "patient-1001") is False


def test_authorizes_assumed_role_and_patient_patterns(monkeypatch) -> None:
    principal = "arn:aws:sts::111111111111:assumed-role/dashboard-role/session-name"
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", json.dumps({"arn:aws:sts::111111111111:assumed-role/dashboard-role/*": ["load_test_patient_*"]}))
    event = {"requestContext": {"identity": {"userArn": principal}}}

    assert is_patient_authorized(event, "load_test_patient_01") is True


def test_denies_missing_identity_and_invalid_policy(monkeypatch) -> None:
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", "not-json")

    assert load_patient_access_policy() == {}
    assert is_patient_authorized({}, "patient-1000") is False


def test_discards_malformed_policy_entries(monkeypatch) -> None:
    monkeypatch.setenv("PATIENT_ACCESS_POLICY", json.dumps({"valid": ["patient-1000"], "invalid": "patient-1001", "mixed": [1]}))

    assert load_patient_access_policy() == {"valid": ["patient-1000"]}
