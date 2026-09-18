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


def test_teardown_can_resume_after_deployment_outputs_are_removed() -> None:
    script = (REPO_ROOT / "scripts" / "infrastructure" / "teardown.sh").read_text(encoding="utf-8")
    destroy_block = script.split("  destroy-plan)", maxsplit=1)[1].split("  destroy-apply)", maxsplit=1)[0]

    assert "output -raw raw_s3_bucket_name 2>/dev/null || true" in script
    assert "output -json private_subnet_ids >/dev/null 2>&1" in script
    assert "build_or_verify_destroy_packages" in destroy_block
    assert "build_packages" not in destroy_block
    assert "healthcare_realtime_mwaa_serverless_code.zip" in script
