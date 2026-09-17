from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from scripts.infrastructure.check_region_readiness import run_checks


class Paginator:
    def __init__(self, name: str, database_pages: list[list[dict[str, str]]] | None = None) -> None:
        self.name = name
        self.database_pages = database_pages or [[]]

    def paginate(self, **kwargs: object) -> list[dict[str, object]]:
        if self.name == "list_policies":
            assert kwargs == {"Scope": "Local"}
            return [{"Policies": []}]
        assert self.name == "describe_db_instances"
        assert kwargs == {}
        return [{"DBInstances": databases} for databases in self.database_pages]


class Client:
    def __init__(self, service: str) -> None:
        self.service = service

    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": "111111111111"}

    def describe_availability_zones(self, **kwargs: object) -> dict[str, object]:
        assert kwargs == {"Filters": [{"Name": "state", "Values": ["available"]}]}
        return {"AvailabilityZones": [{"ZoneName": "example-a"}, {"ZoneName": "example-b"}]}

    def describe_type(self, **kwargs: object) -> dict[str, str]:
        assert kwargs["TypeName"] == "AWS::MWAAServerless::Workflow"
        return {"Arn": "example"}

    def get_account_summary(self) -> dict[str, object]:
        return {"SummaryMap": {"PoliciesQuota": 1500, "Policies": 0}}

    def get_paginator(self, name: str) -> Paginator:
        assert name in {"list_policies", "describe_db_instances"}
        return Paginator(name)

    def describe_vpcs(self) -> dict[str, object]:
        return {"Vpcs": []}

    def describe_addresses(self) -> dict[str, object]:
        return {"Addresses": []}

    def get_service_quota(self, **kwargs: str) -> dict[str, object]:
        values = {("vpc", "L-F678F1CE"): 5.0, ("ec2", "L-0263D0A3"): 5.0, ("fargate", "L-3032A538"): 6.0, ("rds", "L-7B6409FD"): 40.0}
        return {"Quota": {"Value": values[(kwargs["ServiceCode"], kwargs["QuotaCode"])]}}

    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["Namespace"] == "AWS/Usage"
        assert kwargs["MetricName"] == "ResourceCount"
        assert kwargs["Statistics"] == ["Maximum"]
        return {"Datapoints": [{"Maximum": 1.5}]}


class Session:
    def client(self, service: str) -> Any:
        return Client(service)


def test_empty_account_region_is_ready_for_bootstrap() -> None:
    checks = run_checks(Session(), {"policy-one", "policy-two"})

    assert checks
    assert all(check.passed for check in checks)


class OneZoneClient(Client):
    def describe_availability_zones(self, **kwargs: object) -> dict[str, object]:
        return {"AvailabilityZones": [{"ZoneName": "example-a"}]}


class OneZoneSession(Session):
    def client(self, service: str) -> Any:
        if service == "ec2":
            return OneZoneClient(service)
        return Client(service)


def test_region_requires_two_availability_zones() -> None:
    checks = run_checks(OneZoneSession(), set())

    availability_check = next(check for check in checks if check.name == "Availability Zones")
    assert not availability_check.passed


class SaturatedFargateClient(Client):
    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        return {"Datapoints": [{"Maximum": 5.0}]}


class SaturatedFargateSession(Session):
    def client(self, service: str) -> Any:
        if service == "cloudwatch":
            return SaturatedFargateClient(service)
        return Client(service)


def test_region_requires_available_fargate_capacity() -> None:
    checks = run_checks(SaturatedFargateSession(), set())

    fargate_check = next(check for check in checks if check.name == "Fargate quota")
    assert not fargate_check.passed
    assert fargate_check.detail == "1 free of 6; 2 required"


class MissingMwaaClient(Client):
    def describe_type(self, **kwargs: object) -> dict[str, str]:
        raise ClientError({"Error": {"Code": "TypeNotFoundException", "Message": "not found"}}, "DescribeType")


class MissingMwaaSession(Session):
    def client(self, service: str) -> Any:
        if service == "cloudformation":
            return MissingMwaaClient(service)
        return Client(service)


def test_unavailable_mwaa_resource_type_is_reported() -> None:
    checks = run_checks(MissingMwaaSession(), set())

    mwaa_check = next(check for check in checks if check.name == "MWAA Serverless")
    assert not mwaa_check.passed
    assert "unavailable" in mwaa_check.detail


class DeniedMwaaClient(Client):
    def describe_type(self, **kwargs: object) -> dict[str, str]:
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "DescribeType")


class DeniedMwaaSession(Session):
    def client(self, service: str) -> Any:
        if service == "cloudformation":
            return DeniedMwaaClient(service)
        return Client(service)


def test_mwaa_permission_errors_are_not_misreported_as_unavailable() -> None:
    with pytest.raises(ClientError, match="AccessDeniedException"):
        run_checks(DeniedMwaaSession(), set())


class PaginatedRdsClient(Client):
    def get_paginator(self, name: str) -> Paginator:
        assert name == "describe_db_instances"
        return Paginator(name, [[{"DBInstanceIdentifier": "one"}], [{"DBInstanceIdentifier": "two"}]])


class PaginatedRdsSession(Session):
    def client(self, service: str) -> Any:
        if service == "rds":
            return PaginatedRdsClient(service)
        return Client(service)


def test_rds_quota_counts_all_pages() -> None:
    checks = run_checks(PaginatedRdsSession(), set())

    rds_check = next(check for check in checks if check.name == "RDS quota")
    assert rds_check.detail == "38 free; 2 required"
