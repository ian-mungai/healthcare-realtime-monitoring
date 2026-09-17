from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "infrastructure" / "render_project_config.py"
SPEC = importlib.util.spec_from_file_location("render_project_config", MODULE_PATH)
assert SPEC and SPEC.loader
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


def environment() -> dict[str, str]:
    return {
        "AWS_ACCOUNT_ID": "111111111111",
        "AWS_REGION": "us-west-2",
        "TF_STATE_REGION": "us-east-1",
        "PROJECT_NAME": "healthcare-realtime-monitoring",
        "TF_STATE_BUCKET": "example-state-bucket",
        "DATA_BUCKET_NAME": "example-data-bucket",
        "MWAA_SOURCE_BUCKET_NAME": "example-mwaa-bucket",
        "REALTIME_ALERT_EMAIL": "alerts@example.com",
        "GITHUB_REPOSITORY": "example/healthcare-realtime-monitoring",
        "GITHUB_DEPLOYMENT_ENVIRONMENT": "development",
        "GITHUB_OIDC_SUBJECT_PREFIX": "repo:example@1/healthcare-realtime-monitoring@2",
        "ENABLE_GITHUB_OIDC": "true",
        "FHIR_WEBHOOK_SECRET_ID": "healthcare-realtime/fhir-webhook",
        "PATIENT_IDS": ",".join(f"patient-{number:02d}" for number in range(1, 11)),
        "REALTIME_PATIENT_ACCESS_PRINCIPALS": "arn:aws:iam::111111111111:user/dashboard",
        "ENABLE_OPENLINEAGE_COLLECTOR": "true",
        "OPENLINEAGE_COLLECTOR_DESIRED_COUNT": "1",
        "OPENLINEAGE_COLLECTOR_URL": "",
        "VITALS_SIMULATOR_IMAGE_TAG": "sha-example",
        "DBT_IMAGE_TAG": "sha-example",
        "SODA_IMAGE_TAG": "sha-example",
        "OPENLINEAGE_COLLECTOR_IMAGE_TAG": "sha-example",
        "ML_APPROVED_MODEL_VERSION": "",
    }


def defaults() -> dict[str, object]:
    return json.loads((REPO_ROOT / "config" / "deployment.defaults.json").read_text(encoding="utf-8"))


def test_build_configuration_derives_shared_values() -> None:
    deployment, bootstrap = renderer.build_configuration(environment(), defaults())

    patients = [f"patient-{number:02d}" for number in range(1, 11)]
    assert deployment["active_patient_ids"] == patients
    assert deployment["realtime_patient_access_policy"] == {"arn:aws:iam::111111111111:user/dashboard": patients}
    assert deployment["athena_results_s3_uri"] == "s3://example-data-bucket/athena_results/"
    assert len(deployment["github_deployment_policy_arns"]) == 20
    assert all(arn.startswith("arn:aws:iam::111111111111:policy/") for arn in deployment["github_deployment_policy_arns"])
    assert bootstrap == {"aws_region": "us-east-1", "project_name": "healthcare-realtime-monitoring", "state_bucket_name": "example-state-bucket"}


def test_patient_ids_must_be_exactly_ten() -> None:
    values = environment()
    values["PATIENT_IDS"] = "patient-01,patient-02"

    with pytest.raises(renderer.ConfigurationError, match="exactly ten"):
        renderer.build_configuration(values, defaults())


def test_new_install_uses_bootstrap_image_tags_until_images_are_published() -> None:
    values = environment()
    for name in renderer.GENERATED_STRING_VARIABLES:
        values.pop(name)

    deployment, _ = renderer.build_configuration(values, defaults())

    assert {deployment[name] for name in renderer.GENERATED_STRING_VARIABLES.values()} == {"sha-bootstrap"}


def test_build_configuration_ignores_ambient_shell_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "conflicting-region")

    deployment, bootstrap = renderer.build_configuration(environment(), defaults())

    assert deployment["aws_region"] == "us-west-2"
    assert bootstrap["aws_region"] == "us-east-1"


def test_write_or_check_detects_stale_generated_file(tmp_path: Path) -> None:
    output = tmp_path / "deployment.auto.tfvars.json"
    content = renderer.rendered_json({"aws_region": "us-west-2"})
    renderer.write_or_check(output, content, check=False)
    renderer.write_or_check(output, content, check=True)

    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(renderer.ConfigurationError, match="stale"):
        renderer.write_or_check(output, content, check=True)
