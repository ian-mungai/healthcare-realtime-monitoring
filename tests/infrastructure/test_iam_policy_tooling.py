from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_s3_policy.json"
ECR_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_ecr_policy.json"
RENDERER_PATH = REPO_ROOT / "infra/iam/scripts/render_policy.py"
EXPORTER_PATH = REPO_ROOT / "infra/iam/scripts/export_policies.py"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_state_policy_limits_object_access_to_backend_prefix() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}

    assert statements["ManageTerraformStateBucket"]["Resource"] == "arn:aws:s3:::${TF_STATE_BUCKET}"
    assert statements["ManageTerraformStateObjects"]["Resource"] == ("arn:aws:s3:::${TF_STATE_BUCKET}/${PROJECT_NAME}/terraform/*")
    assert "s3:DeleteBucket" not in statements["ManageTerraformStateBucket"]["Action"]


def test_ecr_policy_can_read_image_scan_findings() -> None:
    policy = json.loads(ECR_POLICY_PATH.read_text(encoding="utf-8"))
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}

    actions = statements["ManageHealthcareRealtimeRepositories"]["Action"]
    assert "ecr:DescribeImageScanFindings" in actions
    assert "ecr:StartImageScan" in actions


def test_renderer_replaces_state_bucket_placeholder(tmp_path: Path) -> None:
    rendered_path = tmp_path / "s3-policy.json"
    environment = {
        **os.environ,
        "AWS_ACCOUNT_ID": "111111111111",
        "AWS_REGION": "example-region-1",
        "DATA_BUCKET_NAME": "example-data",
        "MWAA_BUCKET_NAME": "example-mwaa",
        "TF_STATE_BUCKET": "example-state",
        "PROJECT_NAME": "example-project",
    }

    subprocess.run([sys.executable, str(RENDERER_PATH), str(POLICY_PATH), "--output", str(rendered_path)], check=True, env=environment)

    rendered = rendered_path.read_text(encoding="utf-8")
    assert "${TF_STATE_BUCKET}" not in rendered
    assert "arn:aws:s3:::example-state/example-project/terraform/*" in rendered


def test_exporter_redacts_state_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = load_module(EXPORTER_PATH, "export_policies_for_test")
    monkeypatch.setenv("TF_STATE_BUCKET", "private-state-bucket")

    assert exporter.sanitize_string("arn:aws:s3:::private-state-bucket/example-project/terraform/terraform.tfstate") == (
        "arn:aws:s3:::${TF_STATE_BUCKET}/example-project/terraform/terraform.tfstate"
    )
