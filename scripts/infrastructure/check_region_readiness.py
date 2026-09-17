from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

MWAA_SERVERLESS_TYPE = "AWS::MWAAServerless::Workflow"
VPC_QUOTA_CODE = "L-F678F1CE"
ELASTIC_IP_QUOTA_CODE = "L-0263D0A3"
FARGATE_VCPU_QUOTA_CODE = "L-3032A538"
FARGATE_REQUIRED_VCPUS = 2.0
RDS_INSTANCE_QUOTA_CODE = "L-7B6409FD"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def quota_value(service_quotas: Any, service_code: str, quota_code: str) -> float:
    response = service_quotas.get_service_quota(ServiceCode=service_code, QuotaCode=quota_code)
    return float(response["Quota"]["Value"])


def fargate_usage_vcpus(cloudwatch: Any) -> float:
    end_time = datetime.now(UTC)
    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/Usage",
        MetricName="ResourceCount",
        Dimensions=[
            {"Name": "Service", "Value": "Fargate"},
            {"Name": "Type", "Value": "Resource"},
            {"Name": "Resource", "Value": "vCPU"},
            {"Name": "Class", "Value": "Standard/OnDemand"},
        ],
        StartTime=end_time - timedelta(minutes=5),
        EndTime=end_time,
        Period=60,
        Statistics=["Maximum"],
    )
    return max((float(point["Maximum"]) for point in response.get("Datapoints", [])), default=0.0)


def run_checks(session: Any, policy_template_names: set[str]) -> list[Check]:
    checks: list[Check] = []
    session.client("sts").get_caller_identity()

    ec2 = session.client("ec2")
    zones = ec2.describe_availability_zones(Filters=[{"Name": "state", "Values": ["available"]}])["AvailabilityZones"]
    checks.append(Check("Availability Zones", len(zones) >= 2, f"{len(zones)} available; 2 required"))

    cloudformation = session.client("cloudformation")
    try:
        cloudformation.describe_type(Type="RESOURCE", TypeName=MWAA_SERVERLESS_TYPE)
        checks.append(Check("MWAA Serverless", True, "CloudFormation resource type is available"))
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "TypeNotFoundException":
            checks.append(Check("MWAA Serverless", False, "CloudFormation resource type is unavailable in this region"))
        else:
            raise

    iam = session.client("iam")
    iam_summary = iam.get_account_summary()["SummaryMap"]
    existing_policy_names: set[str] = set()
    for page in iam.get_paginator("list_policies").paginate(Scope="Local"):
        existing_policy_names.update(policy["PolicyName"] for policy in page.get("Policies", []))
    missing_policy_count = len(policy_template_names - existing_policy_names)
    policy_slots = int(iam_summary["PoliciesQuota"]) - int(iam_summary["Policies"])
    checks.append(Check("IAM policy capacity", policy_slots >= missing_policy_count, f"{policy_slots} free; {missing_policy_count} required"))

    service_quotas = session.client("service-quotas")
    vpc_count = len(ec2.describe_vpcs()["Vpcs"])
    vpc_quota = quota_value(service_quotas, "vpc", VPC_QUOTA_CODE)
    checks.append(Check("VPC quota", vpc_quota - vpc_count >= 1, f"{int(vpc_quota - vpc_count)} free; 1 required"))

    address_count = len(ec2.describe_addresses()["Addresses"])
    address_quota = quota_value(service_quotas, "ec2", ELASTIC_IP_QUOTA_CODE)
    checks.append(Check("Elastic IP quota", address_quota - address_count >= 1, f"{int(address_quota - address_count)} free; 1 required"))

    fargate_quota = quota_value(service_quotas, "fargate", FARGATE_VCPU_QUOTA_CODE)
    fargate_usage = fargate_usage_vcpus(session.client("cloudwatch"))
    fargate_available = max(fargate_quota - fargate_usage, 0.0)
    checks.append(
        Check(
            "Fargate quota",
            fargate_available >= FARGATE_REQUIRED_VCPUS,
            f"{fargate_available:g} free of {fargate_quota:g}; {FARGATE_REQUIRED_VCPUS:g} required",
        )
    )

    rds = session.client("rds")
    database_count = sum(len(page.get("DBInstances", [])) for page in rds.get_paginator("describe_db_instances").paginate())
    database_quota = quota_value(service_quotas, "rds", RDS_INSTANCE_QUOTA_CODE)
    checks.append(Check("RDS quota", database_quota - database_count >= 2, f"{int(database_quota - database_count)} free; 2 required"))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Check regional service availability and capacity before deployment.")
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--policy-directory", type=Path, default=Path("infra/iam/policies"))
    arguments = parser.parse_args()

    policy_names = {path.stem for path in arguments.policy_directory.glob("*.json")}
    session = boto3.Session(profile_name=arguments.profile, region_name=arguments.region)
    try:
        checks = run_checks(session, policy_names)
    except Exception as error:
        raise SystemExit(f"FAIL  readiness check could not complete: {type(error).__name__}: {error}") from error

    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"{status}  {check.name}: {check.detail}")
    failures = [check for check in checks if not check.passed]
    if failures:
        raise SystemExit(f"{len(failures)} regional readiness check(s) failed.")
    print("Regional readiness checks passed.")


if __name__ == "__main__":
    main()
