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
IAM_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_iam_policy.json"
CLOUDFORMATION_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_cloudformation_policy.json"
COST_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_cost_management_policy.json"
RENDERER_PATH = REPO_ROOT / "infra/iam/scripts/render_policy.py"
EXPORTER_PATH = REPO_ROOT / "infra/iam/scripts/export_policies.py"
MANAGER_PATH = REPO_ROOT / "infra/iam/scripts/manage_policies.py"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
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


def test_region_readiness_permissions_are_tracked() -> None:
    documents = [
        json.loads(IAM_POLICY_PATH.read_text(encoding="utf-8")),
        json.loads(CLOUDFORMATION_POLICY_PATH.read_text(encoding="utf-8")),
        json.loads(COST_POLICY_PATH.read_text(encoding="utf-8")),
    ]
    actions = {action for document in documents for statement in document["Statement"] for action in statement["Action"]}

    assert {"iam:GetAccountSummary", "cloudformation:DescribeType", "servicequotas:GetServiceQuota"} <= actions


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


class PolicyPaginator:
    def __init__(self, policies: list[dict[str, object]]) -> None:
        self.policies = policies

    def paginate(self, **kwargs: object) -> list[dict[str, object]]:
        assert kwargs == {"Scope": "Local"}
        return [{"Policies": self.policies}]


class EmptyAccountIam:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def get_paginator(self, name: str) -> PolicyPaginator:
        assert name == "list_policies"
        return PolicyPaginator([])

    def create_policy(self, **kwargs: object) -> None:
        self.created.append(kwargs)


class ExistingAccountIam:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document

    def get_paginator(self, name: str) -> PolicyPaginator:
        assert name == "list_policies"
        return PolicyPaginator(
            [{"PolicyName": "healthcare_realtime_example", "Arn": "arn:aws:iam::111111111111:policy/healthcare_realtime_example", "DefaultVersionId": "v1"}]
        )

    def get_policy_version(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["VersionId"] == "v1"
        return {"PolicyVersion": {"Document": self.document}}


class PartiallyFailingIam:
    def __init__(self) -> None:
        self.created: list[str] = []

    def create_policy(self, **kwargs: object) -> None:
        name = str(kwargs["PolicyName"])
        if name == "healthcare_realtime_example_one":
            raise RuntimeError("simulated IAM failure")
        self.created.append(name)


def test_policy_manager_plans_and_creates_every_policy_in_an_empty_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MANAGER_PATH.parent))
    manager = load_module(MANAGER_PATH, "manage_policies_for_test")
    iam = EmptyAccountIam()
    documents = {
        "healthcare_realtime_example_one": {"Version": "2012-10-17", "Statement": []},
        "healthcare_realtime_example_two": {"Version": "2012-10-17", "Statement": []},
    }

    changes = manager.plan_changes(iam, documents)
    manager.apply_changes(iam, documents, changes)

    assert [change.action for change in changes] == ["create", "create"]
    assert [call["PolicyName"] for call in iam.created] == sorted(documents)


def test_policy_manager_normalizes_aws_scalar_lists_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MANAGER_PATH.parent))
    manager = load_module(MANAGER_PATH, "manage_policies_normalization_for_test")
    stored_document: dict[str, object] = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "servicequotas:GetServiceQuota", "Resource": "*", "Principal": {"Service": "ecs-tasks.amazonaws.com"}},
            {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject"], "Resource": "arn:aws:s3:::example/*"},
        ],
    }
    template_document = {
        "Statement": [
            {"Resource": ["*"], "Principal": {"Service": ["ecs-tasks.amazonaws.com"]}, "Action": ["servicequotas:GetServiceQuota"], "Effect": "Allow"},
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"], "Resource": ["arn:aws:s3:::example/*"]},
        ],
        "Version": "2012-10-17",
    }

    changes = manager.plan_changes(ExistingAccountIam(stored_document), {"healthcare_realtime_example": template_document})

    assert [change.action for change in changes] == ["no-change"]


def test_policy_manager_collects_failures_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MANAGER_PATH.parent))
    manager = load_module(MANAGER_PATH, "manage_policies_failure_manifest_for_test")
    iam = PartiallyFailingIam()
    documents = {
        "healthcare_realtime_example_one": {"Version": "2012-10-17", "Statement": []},
        "healthcare_realtime_example_two": {"Version": "2012-10-17", "Statement": []},
    }
    changes = [manager.PolicyChange(name, "create") for name in sorted(documents)]

    results = manager.apply_changes(iam, documents, changes)

    assert [(result.name, result.status) for result in results] == [
        ("healthcare_realtime_example_one", "failed"),
        ("healthcare_realtime_example_two", "applied"),
    ]
    assert iam.created == ["healthcare_realtime_example_two"]


def test_policy_manager_loads_ignored_environment_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MANAGER_PATH.parent))
    manager = load_module(MANAGER_PATH, "manage_policies_environment_for_test")
    environment_file = tmp_path / ".env"
    environment_file.write_text("AWS_PROFILE=example\nTF_STATE_BUCKET='example-state'\n", encoding="utf-8")

    assert manager.load_environment_file(environment_file) == {"AWS_PROFILE": "example", "TF_STATE_BUCKET": "example-state"}


def test_policy_manager_can_limit_an_update_to_selected_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MANAGER_PATH.parent))
    manager = load_module(MANAGER_PATH, "manage_policies_selection_for_test")
    environment = {"AWS_ACCOUNT_ID": "111111111111", "AWS_REGION": "example-region-1", "PROJECT_NAME": "example-project"}
    terraform_var_file = REPO_ROOT / "config/deployment.defaults.json"

    documents = manager.load_documents(terraform_var_file, environment, {"healthcare_realtime_cloudformation_policy"})

    assert set(documents) == {"healthcare_realtime_cloudformation_policy"}
