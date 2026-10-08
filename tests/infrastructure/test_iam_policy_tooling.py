from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType

import hcl2
import pytest

from testkit import expect
from tools.process import run_command

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_s3_policy.json"
ECR_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_ecr_policy.json"
IAM_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_iam_policy.json"
CLOUDFORMATION_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_cloudformation_policy.json"
COST_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_cost_management_policy.json"
KMS_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_kms_policy.json"
SECRETSMANAGER_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_secretsmanager_policy.json"
EC2_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_ec2_policy.json"
ECS_POLICY_PATH = REPO_ROOT / "infra/iam/policies/healthcare_realtime_ecs_policy.json"
RENDERER_PATH = REPO_ROOT / "infra/iam/scripts/render_policy.py"
EXPORTER_PATH = REPO_ROOT / "infra/iam/scripts/export_policies.py"
MANAGER_PATH = REPO_ROOT / "infra/iam/scripts/manage_policies.py"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if not (spec is not None and spec.loader is not None):
        expect.fail("expected: spec is not None and spec.loader is not None")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_state_policy_limits_object_access_to_backend_prefix() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}

    expect.equal(statements["ManageTerraformStateBucket"]["Resource"], "arn:aws:s3:::${TF_STATE_BUCKET}")
    expect.equal(statements["ManageTerraformStateObjects"]["Resource"], "arn:aws:s3:::${TF_STATE_BUCKET}/${PROJECT_NAME}/terraform/*")
    expect.not_in("s3:DeleteBucket", statements["ManageTerraformStateBucket"]["Action"])


def test_ecr_policy_can_read_image_scan_findings() -> None:
    policy = json.loads(ECR_POLICY_PATH.read_text(encoding="utf-8"))
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}

    actions = statements["ManageHealthcareRealtimeRepositories"]["Action"]
    expect.is_in("ecr:DescribeImageScanFindings", actions)
    expect.is_in("ecr:StartImageScan", actions)


def test_ec2_policy_can_destroy_an_associated_nat_address() -> None:
    # Terraform disassociates the NAT Elastic IP before it releases the address during destroy.
    policy = json.loads(EC2_POLICY_PATH.read_text(encoding="utf-8"))
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}

    actions = statements["ManageHealthcareRealtimeNetwork"]["Action"]
    expect.is_in("ec2:DisassociateAddress", actions)
    expect.is_in("ec2:ReleaseAddress", actions)


def test_region_readiness_permissions_are_tracked() -> None:
    documents = [
        json.loads(IAM_POLICY_PATH.read_text(encoding="utf-8")),
        json.loads(CLOUDFORMATION_POLICY_PATH.read_text(encoding="utf-8")),
        json.loads(COST_POLICY_PATH.read_text(encoding="utf-8")),
    ]
    actions = {action for document in documents for statement in document["Statement"] for action in statement["Action"]}

    if not ({"iam:GetAccountSummary", "cloudformation:DescribeType", "servicequotas:GetServiceQuota"} <= actions):
        expect.fail('expected: {"iam:GetAccountSummary", "cloudformation:DescribeType", "servicequotas:GetServiceQuota"} <= actions')


def test_renderer_replaces_state_bucket_placeholder(tmp_path: Path) -> None:
    rendered_path = tmp_path / "s3-policy.json"
    environment = {
        **os.environ,
        "AWS_ACCOUNT_ID": "111111111111",
        "AWS_REGION": "example-region-1",
        "DATA_BUCKET_NAME": "example-data",
        "TF_STATE_BUCKET": "example-state",
        "PROJECT_NAME": "example-project",
    }

    run_command(sys.executable, [str(RENDERER_PATH), str(POLICY_PATH), "--output", str(rendered_path)], check=True, env=environment)

    rendered = rendered_path.read_text(encoding="utf-8")
    expect.not_in("${TF_STATE_BUCKET}", rendered)
    expect.is_in("arn:aws:s3:::example-state/example-project/terraform/*", rendered)


def test_kms_policy_uses_configured_project_tag(tmp_path: Path) -> None:
    rendered_path = tmp_path / "kms-policy.json"
    environment = {**os.environ, "AWS_ACCOUNT_ID": "111111111111", "AWS_REGION": "example-region-1", "PROJECT_NAME": "example-project"}

    run_command(sys.executable, [str(RENDERER_PATH), str(KMS_POLICY_PATH), "--output", str(rendered_path)], check=True, env=environment)

    document = json.loads(rendered_path.read_text(encoding="utf-8"))
    statements = {statement["Sid"]: statement for statement in document["Statement"]}
    expect.equal(statements["CreateHealthcareRealtimeKmsKeys"]["Condition"]["StringEquals"]["aws:RequestTag/Project"], "example-project")
    expect.equal(statements["ManageHealthcareRealtimeKmsKeys"]["Condition"]["StringEquals"]["aws:ResourceTag/Project"], "example-project")


def test_secretsmanager_policy_reads_only_configured_webhook_secret(tmp_path: Path) -> None:
    rendered_path = tmp_path / "secretsmanager-policy.json"
    environment = {**os.environ, "AWS_ACCOUNT_ID": "111111111111", "AWS_REGION": "example-region-1", "FHIR_WEBHOOK_SECRET_ID": "example-project/fhir-webhook"}

    run_command(sys.executable, [str(RENDERER_PATH), str(SECRETSMANAGER_POLICY_PATH), "--output", str(rendered_path)], check=True, env=environment)

    document = json.loads(rendered_path.read_text(encoding="utf-8"))
    statements = {statement["Sid"]: statement for statement in document["Statement"]}
    webhook_access = statements["ReadFHIRWebhookSecret"]
    expect.equal(webhook_access["Action"], ["secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue"])
    expect.equal(webhook_access["Resource"], "arn:aws:secretsmanager:example-region-1:111111111111:secret:example-project/fhir-webhook-*")


def rendered_statements(tmp_path: Path, source: Path) -> dict[str, dict]:
    rendered_path = tmp_path / source.name
    environment = {**os.environ, "AWS_ACCOUNT_ID": "111111111111", "AWS_REGION": "example-region-1", "FHIR_WEBHOOK_SECRET_ID": "example-project/fhir-webhook"}
    run_command(sys.executable, [str(RENDERER_PATH), str(source), "--output", str(rendered_path)], check=True, env=environment)
    return {statement["Sid"]: statement for statement in json.loads(rendered_path.read_text(encoding="utf-8"))["Statement"]}


def test_the_operator_port_forward_reaches_only_service_tasks_through_the_forwarding_document(tmp_path: Path) -> None:
    """The deploy user opens the Grafana port forward; it must not open shells or sessions on other targets."""
    statements = rendered_statements(tmp_path, ECS_POLICY_PATH)

    start = statements["StartServicePortForward"]
    expect.equal(start["Action"], ["ssm:StartSession"])
    expect.equal(
        sorted(start["Resource"]),
        [
            "arn:aws:ecs:example-region-1:111111111111:task/healthcare-realtime-services/*",
            "arn:aws:ssm:example-region-1::document/AWS-StartPortForwardingSession",
        ],
    )
    expect.equal(statements["EndOwnSessions"]["Resource"], "arn:aws:ssm:example-region-1:111111111111:session/${aws:userid}-*")


def test_the_grafana_secret_is_only_read_by_its_name(tmp_path: Path) -> None:
    """The operator creates the Grafana admin secret; the deploy identity only describes it for Terraform and reads it for e2e."""
    statements = rendered_statements(tmp_path, SECRETSMANAGER_POLICY_PATH)

    grafana = statements["ReadGrafanaAdminSecret"]
    expect.equal(grafana["Resource"], "arn:aws:secretsmanager:example-region-1:111111111111:secret:healthcare-realtime/grafana-admin-*")
    expect.equal(sorted(grafana["Action"]), ["secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue"])


def test_terraform_reads_the_grafana_secret_and_creates_none() -> None:
    """Secret values stay out of Terraform: the stack creates no secret and reads Grafana's by the name the policy scopes."""
    terraform_files = sorted((REPO_ROOT / "infra").glob("**/*.tf"))
    terraform_files = [path for path in terraform_files if ".terraform" not in path.parts]
    for path in terraform_files:
        text = path.read_text(encoding="utf-8")
        expect.equal('resource "aws_secretsmanager_secret' in text, False, f"{path.relative_to(REPO_ROOT)} creates a secret")
        expect.equal("hashicorp/random" in text, False, f"{path.relative_to(REPO_ROOT)} still declares the random provider")

    with (REPO_ROOT / "infra/modules/grafana_ecs/main.tf").open(encoding="utf-8") as stream:
        data_sources = hcl2.load(stream)["data"]
    secrets = [body['"admin"'] for source in data_sources for name, body in source.items() if name == '"aws_secretsmanager_secret"']
    expect.equal([secret["name"].strip('"') for secret in secrets], ["healthcare-realtime/grafana-admin"])


def test_exporter_redacts_state_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = load_module(EXPORTER_PATH, "export_policies_for_test")
    monkeypatch.setenv("TF_STATE_BUCKET", "private-state-bucket")

    expect.equal(
        exporter.sanitize_string("arn:aws:s3:::private-state-bucket/example-project/terraform/terraform.tfstate"),
        "arn:aws:s3:::${TF_STATE_BUCKET}/example-project/terraform/terraform.tfstate",
    )


class PolicyPaginator:
    def __init__(self, policies: list[dict[str, object]]) -> None:
        self.policies = policies

    def paginate(self, **kwargs: object) -> list[dict[str, object]]:
        expect.equal(kwargs, {"Scope": "Local"})
        return [{"Policies": self.policies}]


class EmptyAccountIam:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def get_paginator(self, name: str) -> PolicyPaginator:
        expect.equal(name, "list_policies")
        return PolicyPaginator([])

    def create_policy(self, **kwargs: object) -> None:
        self.created.append(kwargs)


class ExistingAccountIam:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document

    def get_paginator(self, name: str) -> PolicyPaginator:
        expect.equal(name, "list_policies")
        return PolicyPaginator(
            [{"PolicyName": "healthcare_realtime_example", "Arn": "arn:aws:iam::111111111111:policy/healthcare_realtime_example", "DefaultVersionId": "v1"}]
        )

    def get_policy_version(self, **kwargs: object) -> dict[str, object]:
        expect.equal(kwargs["VersionId"], "v1")
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

    expect.equal([change.action for change in changes], ["create", "create"])
    expect.equal([call["PolicyName"] for call in iam.created], sorted(documents))


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

    expect.equal([change.action for change in changes], ["no-change"])


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

    expect.equal(
        [(result.name, result.status) for result in results], [("healthcare_realtime_example_one", "failed"), ("healthcare_realtime_example_two", "applied")]
    )
    expect.equal(iam.created, ["healthcare_realtime_example_two"])


def test_policy_manager_loads_ignored_environment_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MANAGER_PATH.parent))
    manager = load_module(MANAGER_PATH, "manage_policies_environment_for_test")
    environment_file = tmp_path / ".env"
    environment_file.write_text("AWS_PROFILE=example\nTF_STATE_BUCKET='example-state'\n", encoding="utf-8")

    expect.equal(manager.load_environment_file(environment_file), {"AWS_PROFILE": "example", "TF_STATE_BUCKET": "example-state"})


def test_policy_manager_can_limit_an_update_to_selected_templates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(MANAGER_PATH.parent))
    manager = load_module(MANAGER_PATH, "manage_policies_selection_for_test")
    environment = {"AWS_ACCOUNT_ID": "111111111111", "AWS_REGION": "example-region-1", "PROJECT_NAME": "example-project"}
    terraform_var_file = REPO_ROOT / "config/deployment.defaults.json"

    documents = manager.load_documents(terraform_var_file, environment, {"healthcare_realtime_cloudformation_policy"})

    expect.equal(set(documents), {"healthcare_realtime_cloudformation_policy"})


def test_every_policy_placeholder_resolves_from_the_deployment_defaults(tmp_path: Path) -> None:
    """A new placeholder without a renderer mapping stops the policy plan at deploy time (feature-window table, Oct 8 2026)."""
    renderer = load_module(RENDERER_PATH, "render_policy_for_placeholders")
    defaults = json.loads((REPO_ROOT / "config/deployment.defaults.json").read_text(encoding="utf-8"))["terraform"]
    var_file = tmp_path / "deployment.auto.tfvars.json"
    var_file.write_text(json.dumps({**defaults, "aws_region": "example-region-1", "project_name": "example-project", "data_bucket_name": "example-bucket"}))
    environment = {"AWS_ACCOUNT_ID": "111111111111", "TF_STATE_BUCKET": "example-state", "FHIR_WEBHOOK_SECRET_ID": "example-project/fhir-webhook"}

    for source in sorted((REPO_ROOT / "infra/iam/policies").glob("*.json")):
        renderer.render_policy_document(source, var_file, environment)


def test_every_ecr_repository_terraform_creates_is_in_the_ecr_policy() -> None:
    """The policy lists repositories by name; the Grafana repository was missing and its creation was denied (Oct 8 2026)."""
    declared = {
        name
        for path in (REPO_ROOT / "infra").rglob("*.tf")
        for name in re.findall(r'resource "aws_ecr_repository" "\w+" \{\s*name\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"))
    }
    policy = json.loads(ECR_POLICY_PATH.read_text(encoding="utf-8"))
    allowed = {
        resource.rsplit("/", 1)[-1]
        for statement in policy["Statement"]
        if statement.get("Sid") == "ManageHealthcareRealtimeRepositories"
        for resource in statement["Resource"]
    }

    expect.equal(len(declared) >= 5, True, f"found {declared}")
    expect.equal(declared - allowed, set())


def test_the_operator_can_invoke_every_iam_protected_vitals_api_route() -> None:
    """The early-warning route was added without invoke access, so API Gateway refused the operator (Oct 8 2026)."""
    from fnmatch import fnmatchcase

    module = (REPO_ROOT / "infra/modules/vitals_api/main.tf").read_text(encoding="utf-8")
    routes = re.findall(r'route_key\s*=\s*"(\w+) ([^"]+)"\s*\n\s*authorization_type\s*=\s*"AWS_IAM"', module)
    policy = json.loads((REPO_ROOT / "infra/iam/policies/healthcare_realtime_apigateway_policy.json").read_text(encoding="utf-8"))
    invoke = next(statement for statement in policy["Statement"] if statement.get("Sid") == "InvokeHealthcareRealtimeApis")
    patterns = [resource.split("${API_STAGE_NAME}/", 1)[1] for resource in invoke["Resource"] if "${API_STAGE_NAME}/" in resource]

    expect.equal(len(routes) >= 2, True, f"found {routes}")
    for method, path in routes:
        request = f"{method}{re.sub(r'\{[^}]+\}', 'example', path)}"
        expect.equal(any(fnmatchcase(request, pattern) for pattern in patterns), True, f"{method} {path} has no execute-api:Invoke resource")


def test_the_operator_can_read_partitions_in_every_project_database() -> None:
    """The ML predictions table is partitioned by model version; reading it was denied glue:GetPartition (Oct 8 2026)."""
    policy = json.loads((REPO_ROOT / "infra/iam/policies/healthcare_realtime_glue_policy.json").read_text(encoding="utf-8"))
    read = next(statement for statement in policy["Statement"] if statement.get("Sid") == "ReadHealthcareGlueResources")

    expect.is_in("glue:GetPartitions", read["Action"])
    for database in ("SOURCE_DATABASE_NAME", "DBT_DATABASE_NAME", "ML_DATABASE_NAME"):
        expect.is_in(f"arn:aws:glue:${{AWS_REGION}}:${{AWS_ACCOUNT_ID}}:database/${{{database}}}", read["Resource"])
        expect.is_in(f"arn:aws:glue:${{AWS_REGION}}:${{AWS_ACCOUNT_ID}}:table/${{{database}}}/*", read["Resource"])
