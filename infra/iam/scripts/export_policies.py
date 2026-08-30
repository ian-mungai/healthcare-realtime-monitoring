import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

POLICY_NAMES = [
    "healthcare_realtime_apigateway_policy",
    "healthcare_realtime_athena_policy",
    "healthcare_realtime_cloudwatch_policy",
    "healthcare_realtime_cost_management_policy",
    "healthcare_realtime_dynamodb_policy",
    "healthcare_realtime_ec2_policy",
    "healthcare_realtime_ecr_policy",
    "healthcare_realtime_ecs_policy",
    "healthcare_realtime_firehose_policy",
    "healthcare_realtime_glue_policy",
    "healthcare_realtime_iam_policy",
    "healthcare_realtime_kinesis_policy",
    "healthcare_realtime_kms_policy",
    "healthcare_realtime_lambda_policy",
    "healthcare_realtime_logs_policy",
    "healthcare_realtime_mwaa_policy",
    "healthcare_realtime_s3_policy",
    "healthcare_realtime_sns_policy",
    "healthcare_realtime_sqs_policy",
]

OUTPUT_DIRECTORY = Path(__file__).resolve().parents[1] / "policies"


def run_aws(arguments: list[str]) -> Any:
    result = subprocess.run(["aws", *arguments, "--output", "json"], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def get_policy_arn(policy_name: str) -> str:
    policies = run_aws(["iam", "list-policies", "--scope", "Local", "--query", f"Policies[?PolicyName=='{policy_name}']"])

    if len(policies) != 1:
        raise RuntimeError(f"Expected exactly one customer-managed policy named {policy_name}, found {len(policies)}")

    return policies[0]["Arn"]


def get_policy_document(policy_arn: str) -> dict[str, Any]:
    policy = run_aws(["iam", "get-policy", "--policy-arn", policy_arn])
    default_version_id = policy["Policy"]["DefaultVersionId"]

    version = run_aws(["iam", "get-policy-version", "--policy-arn", policy_arn, "--version-id", default_version_id])

    return version["PolicyVersion"]["Document"]


def sanitize_string(value: str) -> str:
    data_bucket_name = os.environ.get("DATA_BUCKET_NAME")
    mwaa_bucket_name = os.environ.get("MWAA_BUCKET_NAME")

    value = re.sub(r"(?<!\d)\d{12}(?!\d)", "${AWS_ACCOUNT_ID}", value)
    value = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "${EMAIL_ADDRESS}", value)

    if mwaa_bucket_name:
        value = value.replace(mwaa_bucket_name, "${MWAA_BUCKET_NAME}")

    if data_bucket_name:
        value = value.replace(data_bucket_name, "${DATA_BUCKET_NAME}")

    return value


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}

    if isinstance(value, list):
        return [sanitize(item) for item in value]

    if isinstance(value, str):
        return sanitize_string(value)

    return value


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    for policy_name in POLICY_NAMES:
        policy_arn = get_policy_arn(policy_name)
        policy_document = get_policy_document(policy_arn)
        sanitized_document = sanitize(policy_document)

        output_path = OUTPUT_DIRECTORY / f"{policy_name}.json"

        output_path.write_text(json.dumps(sanitized_document, indent=2) + "\n", encoding="utf-8")

        print(f"Exported {policy_name} -> {output_path}")


if __name__ == "__main__":
    main()
