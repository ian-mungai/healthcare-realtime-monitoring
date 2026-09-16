from __future__ import annotations

from typing import Any

from scripts.infrastructure.check_region_readiness import run_checks


class Paginator:
    def paginate(self, **kwargs: object) -> list[dict[str, object]]:
        assert kwargs == {"Scope": "Local"}
        return [{"Policies": []}]


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
        assert name == "list_policies"
        return Paginator()

    def describe_vpcs(self) -> dict[str, object]:
        return {"Vpcs": []}

    def describe_addresses(self) -> dict[str, object]:
        return {"Addresses": []}

    def get_service_quota(self, **kwargs: str) -> dict[str, object]:
        values = {("vpc", "L-F678F1CE"): 5.0, ("ec2", "L-0263D0A3"): 5.0, ("fargate", "L-3032A538"): 6.0, ("rds", "L-7B6409FD"): 40.0}
        return {"Quota": {"Value": values[(kwargs["ServiceCode"], kwargs["QuotaCode"])]}}

    def describe_db_instances(self) -> dict[str, object]:
        return {"DBInstances": []}


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
