from pathlib import Path

import hcl2

from testkit import expect

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_aws_providers_use_the_configured_deployment_region() -> None:
    with (REPO_ROOT / "infra" / "providers.tf").open(encoding="utf-8") as stream:
        configuration = hcl2.load(stream)

    providers = {next(iter(provider)): next(iter(provider.values())) for provider in configuration["provider"]}
    expect.equal(providers['"aws"']["region"], "${var.aws_region}")
    expect.equal(providers['"awscc"']["region"], "${var.aws_region}")


def test_foundation_plan_creates_every_output_required_by_application_generation() -> None:
    script = (REPO_ROOT / "scripts" / "infrastructure" / "bootstrap.sh").read_text(encoding="utf-8")
    foundation_block = script.split("  foundation-plan)", maxsplit=1)[1].split("  foundation-apply)", maxsplit=1)[0]

    for target in ("module.network", "module.raw_s3", "module.hapi_ecs", "module.glue", "module.dbt_ecs", "module.soda_ecs"):
        expect.is_in(f"-target={target}", foundation_block)

    expect.is_in('"$REPO_ROOT/scripts/glue/build_lineage_package.sh"', foundation_block)


def test_teardown_can_resume_after_deployment_outputs_are_removed() -> None:
    script = (REPO_ROOT / "scripts" / "infrastructure" / "teardown.sh").read_text(encoding="utf-8")
    destroy_block = script.split("  destroy-plan)", maxsplit=1)[1].split("  destroy-apply)", maxsplit=1)[0]

    expect.is_in("output -raw raw_s3_bucket_name 2>/dev/null || true", script)
    expect.is_in("output -json private_subnet_ids >/dev/null 2>&1", script)
    expect.is_in("build_or_verify_destroy_packages", destroy_block)
    expect.not_in("build_packages", destroy_block)
    expect.is_in("healthcare_realtime_mwaa_serverless_code.zip", script)


def test_storage_cleanup_covers_every_ecr_repository() -> None:
    """cleanup-preview counts and cleanup-apply empties every repository Terraform creates, Grafana included."""
    script = (REPO_ROOT / "scripts" / "infrastructure" / "teardown.sh").read_text(encoding="utf-8")
    cleanup_block = script.split("cleanup_args() {", maxsplit=1)[1].split("\n}\n", maxsplit=1)[0]
    with (REPO_ROOT / "infra" / "outputs.tf").open(encoding="utf-8") as stream:
        outputs = {name.strip('"'): body["value"] for output in hcl2.load(stream)["output"] for name, body in output.items()}

    modules = sorted(
        path.parent.name for path in (REPO_ROOT / "infra" / "modules").glob("*/main.tf") if 'resource "aws_ecr_repository"' in path.read_text(encoding="utf-8")
    )
    expect.equal(cleanup_block.count('--ecr-repository "$'), len(modules))
    for module in modules:
        names = [name for name, value in outputs.items() if value in (f"${{module.{module}.ecr_repository_url}}", f"${{module.{module}.ecr_repository_name}}")]
        expect.equal(any(f"output -raw {name})" in cleanup_block for name in names), True, f"cleanup_args does not read the {module} repository")
