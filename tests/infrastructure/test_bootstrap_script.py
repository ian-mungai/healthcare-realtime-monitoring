from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_aws_providers_use_the_configured_deployment_region() -> None:
    with (REPO_ROOT / "infra" / "providers.tf").open(encoding="utf-8") as stream:
        configuration = hcl2.load(stream)

    providers = {next(iter(provider)): next(iter(provider.values())) for provider in configuration["provider"]}
    assert providers['"aws"']["region"] == "${var.aws_region}"
    assert providers['"awscc"']["region"] == "${var.aws_region}"


def test_foundation_plan_creates_every_output_required_by_application_generation() -> None:
    script = (REPO_ROOT / "scripts" / "infrastructure" / "bootstrap.sh").read_text(encoding="utf-8")
    foundation_block = script.split("  foundation-plan)", maxsplit=1)[1].split("  foundation-apply)", maxsplit=1)[0]

    for target in ("module.network", "module.raw_s3", "module.hapi_ecs", "module.glue", "module.dbt_ecs", "module.soda_ecs"):
        assert f"-target={target}" in foundation_block

    assert '"$REPO_ROOT/scripts/glue/build_lineage_package.sh"' in foundation_block
