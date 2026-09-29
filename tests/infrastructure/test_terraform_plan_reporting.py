import json
import sys
from pathlib import Path

from scripts.infrastructure.sanitize_terraform_output import collect_string_values, sanitize
from testkit import expect
from tools.process import run_command

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_plan_summary_lists_actions_without_values(tmp_path: Path) -> None:
    plan = {
        "resource_changes": [
            {"address": "module.api.aws_lambda_function.webhook", "change": {"actions": ["update"], "before": {"secret": "old"}, "after": {"secret": "new"}}},
            {"address": "module.data.aws_s3_bucket.raw", "change": {"actions": ["delete", "create"]}},
            {"address": 'aws_iam_role_policy_attachment.deploy["arn:aws:iam::123456789012:policy/private"]', "change": {"actions": ["create"]}},
            {"address": "module.data.aws_s3_bucket.noop", "change": {"actions": ["no-op"]}},
        ]
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = run_command(sys.executable, [str(REPO_ROOT / "scripts/infrastructure/summarize_terraform_plan.py"), str(plan_path)], check=True)

    expect.is_in("module.api.aws_lambda_function.webhook", result.stdout)
    expect.is_in("module.data.aws_s3_bucket.raw", result.stdout)
    expect.is_in("replace", result.stdout)
    expect.not_in("old", result.stdout)
    expect.not_in("new", result.stdout)
    expect.not_in("123456789012", result.stdout)
    expect.not_in("private", result.stdout)
    expect.is_in('aws_iam_role_policy_attachment.deploy["<key>"]', result.stdout)
    expect.is_in("Review required", result.stdout)


def test_failed_plan_diagnostics_are_redacted() -> None:
    output = "Error reading s3://private-state: arn:aws:iam::123456789012:role/deploy at abc.execute-api.example-region-1.amazonaws.com/private-prefix"

    sanitized = sanitize(output, ["private-state", "private-prefix"])

    expect.is_in("Error reading", sanitized)
    expect.not_in("private-state", sanitized)
    expect.not_in("private-prefix", sanitized)
    expect.not_in("123456789012", sanitized)
    expect.not_in("abc.execute-api.example-region-1.amazonaws.com", sanitized)


def test_private_json_strings_are_collected_for_redaction() -> None:
    values = {"bucket": "private-data", "nested": {"tables": ["patients", "observations"]}, "enabled": True}

    expect.equal(collect_string_values(values), ["private-data", "patients", "observations"])
