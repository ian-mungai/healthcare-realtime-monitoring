from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from testkit import expect

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "infrastructure" / "render_project_config.py"
SPEC = importlib.util.spec_from_file_location("render_project_config", MODULE_PATH)
if not (SPEC and SPEC.loader):
    expect.fail("expected: SPEC and SPEC.loader")
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


def environment() -> dict[str, str]:
    return {
        "AWS_ACCOUNT_ID": "111111111111",
        "AWS_REGION": "us-west-2",
        "PROJECT_NAME": "healthcare-realtime-monitoring",
        "DATA_BUCKET_NAME": "example-data-bucket",
        "FHIR_RESOURCE_MAP_S3_KEY": "config/vitals_simulator/fhir_resource_map.json",
        "REALTIME_ALERT_EMAIL": "alerts@example.com",
        "FHIR_WEBHOOK_SECRET_ID": "healthcare-realtime/fhir-webhook",
        "REALTIME_PATIENT_ACCESS_PRINCIPALS": "arn:aws:iam::111111111111:user/dashboard",
        "ENABLE_OPENLINEAGE_COLLECTOR": "true",
        "OPENLINEAGE_COLLECTOR_DESIRED_COUNT": "1",
        "VITALS_SIMULATOR_IMAGE_TAG": "sha-example",
        "DBT_IMAGE_TAG": "sha-example",
        "SODA_IMAGE_TAG": "sha-example",
        "OPENLINEAGE_COLLECTOR_IMAGE_TAG": "sha-example",
        "GRAFANA_IMAGE_TAG": "sha-example",
        "ML_APPROVED_MODEL_VERSION": "",
    }


def defaults() -> dict[str, object]:
    return json.loads((REPO_ROOT / "config" / "deployment.defaults.json").read_text(encoding="utf-8"))


def test_build_configuration_derives_shared_values() -> None:
    patients = tuple(f"patient-{number:02d}" for number in range(1, 11))
    deployment = renderer.build_configuration(environment(), defaults(), patients)

    expect.equal(deployment["active_patient_ids"], list(patients))
    expect.equal(deployment["realtime_patient_access_policy"], {"arn:aws:iam::111111111111:user/dashboard": list(patients)})
    expect.equal(deployment["athena_results_s3_uri"], "s3://example-data-bucket/athena_results/")
    expect.equal(deployment["fhir_resource_map_s3_key"], "config/vitals_simulator/fhir_resource_map.json")
    expect.equal("github_deployment_policy_arns" in deployment, False)


def test_generated_patient_ids_must_be_exactly_ten() -> None:
    with pytest.raises(renderer.ConfigurationError, match="exactly ten"):
        renderer.build_configuration(environment(), defaults(), ("patient-01", "patient-02"))


def test_missing_resource_map_uses_internal_bootstrap_patient_ids() -> None:
    deployment = renderer.build_configuration(environment(), defaults())

    expect.equal(deployment["active_patient_ids"], [f"bootstrap-patient-{number:02d}" for number in range(1, 11)])


def test_new_install_uses_bootstrap_image_tags_until_images_are_published() -> None:
    values = environment()
    for name in renderer.GENERATED_STRING_VARIABLES:
        values.pop(name)

    deployment = renderer.build_configuration(values, defaults())

    expect.equal({deployment[name] for name in renderer.GENERATED_STRING_VARIABLES.values()}, {"sha-bootstrap"})


def test_external_openlineage_url_is_an_optional_explicit_override() -> None:
    deployment = renderer.build_configuration(environment(), defaults())
    expect.equal(deployment["external_openlineage_collector_url"], "")

    values = environment()
    values["EXTERNAL_OPENLINEAGE_COLLECTOR_URL"] = "https://lineage.example.com"
    deployment = renderer.build_configuration(values, defaults())

    expect.equal(deployment["external_openlineage_collector_url"], "https://lineage.example.com")


def test_build_configuration_ignores_ambient_shell_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "conflicting-region")

    deployment = renderer.build_configuration(environment(), defaults())

    expect.equal(deployment["aws_region"], "us-west-2")


def test_write_or_check_detects_stale_generated_file(tmp_path: Path) -> None:
    output = tmp_path / "deployment.auto.tfvars.json"
    content = renderer.rendered_json({"aws_region": "us-west-2"})
    renderer.write_or_check(output, content, check=False)
    renderer.write_or_check(output, content, check=True)

    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(renderer.ConfigurationError, match="stale"):
        renderer.write_or_check(output, content, check=True)
