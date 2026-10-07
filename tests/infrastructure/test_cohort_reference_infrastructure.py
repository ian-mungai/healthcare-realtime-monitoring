"""The AWS path of the cohort reference tables: Glue tables, least-privilege IAM and the daily workflow task.

Failure modes (written before the Terraform):

1. A Glue table's columns drift from what the extract writes: Athena reads nulls or fails. The columns match exactly.
2. The reference objects land under the raw prefix the Glue job reads recursively: they get their own prefix.
3. The setup task cannot read the resource map it needs, or can write outside its prefix: it reads the map and writes
   only under the reference prefix.
4. dbt cannot read the reference objects through Athena: its S3 read scope includes the prefix.
5. MWAA cannot start the setup task, or can pass other roles: RunTask and PassRole name the setup task only.
"""

from __future__ import annotations

import re
from pathlib import Path

from jobs.cohort_reference.extract import TABLES
from testkit import expect

ROOT = Path(__file__).resolve().parents[2]


def module(name: str) -> str:
    return (ROOT / "infra/modules" / name / "main.tf").read_text(encoding="utf-8")


def statement(text: str, sid: str) -> str:
    match = re.search(rf'sid\s*=\s*"{sid}"(?P<body>.*?)(?=\n\s*statement\s*\{{|\n\}})', text, re.DOTALL)
    if match is None:
        expect.fail(f"expected: an IAM statement {sid}")
    return match.group("body")


def test_glue_reference_tables_match_the_extract_columns() -> None:
    block = re.search(r"cohort_reference_tables\s*=\s*\{(?P<body>.*?)\n  \}", module("glue"), re.DOTALL)
    if block is None:
        expect.fail("expected: a cohort_reference_tables map in the Glue module")
    tables = {name: re.findall(r'"([a-z_]+)"', columns) for name, columns in re.findall(r"(\w+)\s*=\s*\[([^\]]*)\]", block.group("body"))}

    expect.equal(tables, {table: list(columns) for table, (columns, _ddl) in TABLES.items()})


def test_reference_objects_have_their_own_prefix_and_least_privilege_access() -> None:
    root = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    prefix = re.search(r'cohort_reference_s3_prefix\s*=\s*"([^"]+)"', root)
    if prefix is None or prefix.group(1).startswith("raw/"):
        expect.fail("expected: a cohort reference prefix outside raw/ in infra/main.tf")

    setup = module("fhir_setup_ecs")
    expect.is_in("${var.cohort_reference_s3_prefix}/*", statement(setup, "WriteCohortReference"))
    expect.is_in("s3:PutObject", statement(setup, "WriteCohortReference"))
    expect.is_in("${var.resource_map_s3_key}", statement(setup, "ReadResourceMap"))
    expect.is_in('name = "COHORT_REFERENCE_S3_PREFIX"', setup)
    expect.is_in("${var.cohort_reference_s3_prefix}/*", statement(module("dbt_ecs"), "ReadProcessedHealthcareData"))


def test_mwaa_may_start_only_the_setup_task_and_pass_only_its_roles() -> None:
    mwaa = module("mwaa")

    expect.is_in("${var.fhir_setup_ecs_task_definition_family}:*", statement(mwaa, "RunHealthcareDataTasks"))
    passed = statement(mwaa, "PassHealthcareDataTaskRoles")
    for role in ("var.fhir_setup_ecs_task_role_arn", "var.fhir_setup_ecs_task_execution_role_arn"):
        expect.is_in(role, passed)
