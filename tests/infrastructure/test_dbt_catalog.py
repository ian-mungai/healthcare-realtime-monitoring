from pathlib import Path

from testkit import expect

DBT_TERRAFORM = Path("infra/modules/dbt_ecs/main.tf")


def test_terraform_owns_dbt_catalog_database() -> None:
    content = DBT_TERRAFORM.read_text()

    expect.is_in('resource "aws_glue_catalog_database" "dbt"', content)
    expect.is_in("name = var.dbt_database_name", content)


def test_dbt_task_does_not_create_catalog_databases() -> None:
    content = DBT_TERRAFORM.read_text()

    expect.not_in('"glue:CreateDatabase"', content)
