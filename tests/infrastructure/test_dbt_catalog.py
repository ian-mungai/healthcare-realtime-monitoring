from pathlib import Path

DBT_TERRAFORM = Path("infra/modules/dbt_ecs/main.tf")


def test_terraform_owns_dbt_catalog_database() -> None:
    content = DBT_TERRAFORM.read_text()

    assert 'resource "aws_glue_catalog_database" "dbt"' in content
    assert "name = var.dbt_database_name" in content


def test_dbt_task_does_not_create_catalog_databases() -> None:
    content = DBT_TERRAFORM.read_text()

    assert '"glue:CreateDatabase"' not in content
