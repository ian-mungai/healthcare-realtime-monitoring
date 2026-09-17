from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from render_policy import render_policy_document

POLICIES_DIRECTORY = Path(__file__).resolve().parents[1] / "policies"
CONFIRMATION = "apply-healthcare-realtime-policies"
IAM_SCALAR_OR_LIST_FIELDS = {"Action", "NotAction", "Resource", "NotResource", "Principal", "NotPrincipal"}


@dataclass(frozen=True)
class PolicyChange:
    name: str
    action: str
    arn: str | None = None


@dataclass(frozen=True)
class PolicyApplyResult:
    name: str
    action: str
    status: str
    detail: str


def load_environment_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid environment assignment at {path}:{line_number}")
        name, value = line.split("=", 1)
        if not name.replace("_", "a").isalnum() or name[0].isdigit():
            raise ValueError(f"invalid environment name at {path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def normalize_iam_value(value: Any, normalize_lists: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: normalize_iam_value(child, normalize_lists or key in IAM_SCALAR_OR_LIST_FIELDS) for key, child in sorted(value.items())}
    if isinstance(value, list):
        normalized = [normalize_iam_value(child, normalize_lists) for child in value]
        if not normalize_lists:
            return normalized
        normalized.sort(key=lambda child: json.dumps(child, sort_keys=True, separators=(",", ":")))
        return normalized[0] if len(normalized) == 1 else normalized
    return value


def canonical(document: dict[str, Any]) -> str:
    normalized = normalize_iam_value(document)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def list_local_policies(iam: Any) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    paginator = iam.get_paginator("list_policies")
    for page in paginator.paginate(Scope="Local"):
        for policy in page.get("Policies", []):
            policies[policy["PolicyName"]] = policy
    return policies


def current_document(iam: Any, policy: dict[str, Any]) -> dict[str, Any]:
    version = iam.get_policy_version(PolicyArn=policy["Arn"], VersionId=policy["DefaultVersionId"])
    return version["PolicyVersion"]["Document"]


def plan_changes(iam: Any, documents: dict[str, dict[str, Any]]) -> list[PolicyChange]:
    existing = list_local_policies(iam)
    changes: list[PolicyChange] = []
    for name, document in sorted(documents.items()):
        policy = existing.get(name)
        if policy is None:
            changes.append(PolicyChange(name, "create"))
        elif canonical(current_document(iam, policy)) == canonical(document):
            changes.append(PolicyChange(name, "no-change", policy["Arn"]))
        else:
            changes.append(PolicyChange(name, "update", policy["Arn"]))
    return changes


def remove_oldest_nondefault_version(iam: Any, policy_arn: str) -> None:
    versions = iam.list_policy_versions(PolicyArn=policy_arn)["Versions"]
    if len(versions) < 5:
        return
    candidates = sorted((version for version in versions if not version["IsDefaultVersion"]), key=lambda version: version["CreateDate"])
    if not candidates:
        raise RuntimeError("policy has five versions but no removable nondefault version")
    iam.delete_policy_version(PolicyArn=policy_arn, VersionId=candidates[0]["VersionId"])


def apply_changes(iam: Any, documents: dict[str, dict[str, Any]], changes: list[PolicyChange]) -> list[PolicyApplyResult]:
    results: list[PolicyApplyResult] = []
    for change in changes:
        if change.action == "no-change":
            results.append(PolicyApplyResult(change.name, change.action, "unchanged", "policy already matches the template"))
            continue
        document = json.dumps(documents[change.name], separators=(",", ":"))
        try:
            if change.action == "create":
                iam.create_policy(PolicyName=change.name, PolicyDocument=document, Description="Healthcare realtime monitoring deployment policy")
            elif change.action == "update":
                if change.arn is None:
                    raise RuntimeError(f"missing ARN for policy update: {change.name}")
                # IAM permits five versions, so capacity must be freed before creating version six.
                remove_oldest_nondefault_version(iam, change.arn)
                iam.create_policy_version(PolicyArn=change.arn, PolicyDocument=document, SetAsDefault=True)
            else:
                raise ValueError(f"unsupported policy action: {change.action}")
        except Exception as error:
            results.append(PolicyApplyResult(change.name, change.action, "failed", f"{type(error).__name__}: {error}"))
        else:
            results.append(PolicyApplyResult(change.name, change.action, "applied", "completed"))
    return results


def load_documents(terraform_var_file: Path, environment: dict[str, str], selected_policies: set[str] | None = None) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted(POLICIES_DIRECTORY.glob("*.json")):
        if selected_policies and path.stem not in selected_policies:
            continue
        documents[path.stem] = render_policy_document(path, terraform_var_file, environment)
    if not documents:
        raise RuntimeError(f"no policy templates found in {POLICIES_DIRECTORY}")
    if selected_policies:
        missing = selected_policies - set(documents)
        if missing:
            raise ValueError(f"unknown policy template(s): {', '.join(sorted(missing))}")
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or apply all tracked customer-managed IAM policy templates.")
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("--terraform-var-file", type=Path, default=Path("infra/deployment.auto.tfvars.json"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--profile")
    parser.add_argument("--region")
    parser.add_argument("--policy", action="append", dest="policies", help="Limit the operation to one tracked policy name. Repeat as needed.")
    arguments = parser.parse_args()

    environment = load_environment_file(arguments.env_file)
    profile = arguments.profile or environment.get("AWS_PROFILE")
    region = arguments.region or environment.get("AWS_REGION")
    session = boto3.Session(profile_name=profile, region_name=region)
    account_id = session.client("sts").get_caller_identity()["Account"]
    environment["AWS_ACCOUNT_ID"] = account_id
    documents = load_documents(arguments.terraform_var_file, environment, set(arguments.policies) if arguments.policies else None)
    iam = session.client("iam")
    changes = plan_changes(iam, documents)

    for change in changes:
        print(f"{change.action.upper():9} {change.name}")

    actionable = [change for change in changes if change.action != "no-change"]
    print(f"Summary: {len(actionable)} change(s), {len(changes) - len(actionable)} unchanged.")

    if arguments.action == "apply":
        if os.environ.get("CONFIRM_IAM_POLICIES") != CONFIRMATION:
            parser.error(f"set CONFIRM_IAM_POLICIES={CONFIRMATION} before applying")
        results = apply_changes(iam, documents, changes)
        print("Apply results:")
        for result in results:
            print(f"{result.status.upper():9} {result.action.upper():9} {result.name}: {result.detail}")
        failures = [result for result in results if result.status == "failed"]
        if failures:
            raise SystemExit(f"{len(failures)} customer-managed policy update(s) failed.")
        applied = sum(result.status == "applied" for result in results)
        unchanged = sum(result.status == "unchanged" for result in results)
        print(f"Customer-managed policy templates applied: {applied} changed, {unchanged} unchanged.")


if __name__ == "__main__":
    main()
