import json
import subprocess
import sys
from pathlib import Path

from scripts.infrastructure.sanitize_terraform_output import collect_string_values, sanitize

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

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/infrastructure/summarize_terraform_plan.py"), str(plan_path)], check=True, capture_output=True, text=True
    )

    assert "module.api.aws_lambda_function.webhook" in result.stdout
    assert "module.data.aws_s3_bucket.raw" in result.stdout
    assert "replace" in result.stdout
    assert "old" not in result.stdout
    assert "new" not in result.stdout
    assert "123456789012" not in result.stdout
    assert "private" not in result.stdout
    assert 'aws_iam_role_policy_attachment.deploy["<key>"]' in result.stdout
    assert "Review required" in result.stdout


def test_failed_plan_diagnostics_are_redacted() -> None:
    output = "Error reading s3://private-state: arn:aws:iam::123456789012:role/deploy at abc.execute-api.example-region-1.amazonaws.com/private-prefix"

    sanitized = sanitize(output, ["private-state", "private-prefix"])

    assert "Error reading" in sanitized
    assert "private-state" not in sanitized
    assert "private-prefix" not in sanitized
    assert "123456789012" not in sanitized
    assert "abc.execute-api.example-region-1.amazonaws.com" not in sanitized


def test_private_json_strings_are_collected_for_redaction() -> None:
    values = {"bucket": "private-data", "nested": {"tables": ["patients", "observations"]}, "enabled": True}

    assert collect_string_values(values) == ["private-data", "patients", "observations"]
