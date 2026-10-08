from pathlib import Path

import hcl2

from testkit import expect
from tools.process import run_command

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


# Terraform state stays local and is not kept after teardown (owner decision, Oct 8 2026): no state bucket, no
# bootstrap stack, no remote backend and no deploy workflow that would need one.
STATE_BUCKET_TERMS = ("TF_STATE_BUCKET", "TF_STATE_PREFIX", "backend.hcl", "sync_deployment_config", "state-backup", "infra/bootstrap")
HISTORY = ("CHANGELOG.md", "docs/release-notes-v1.0.0.md", "docs/release-notes-v1.0.1.md")


def test_terraform_state_stays_local() -> None:
    with (REPO_ROOT / "infra" / "versions.tf").open(encoding="utf-8") as stream:
        settings = hcl2.load(stream)["terraform"][0]
    expect.equal("backend" in settings, False, "infra/versions.tf declares a remote backend")

    tracked = run_command("git", ["ls-files"], cwd=REPO_ROOT, check=True).stdout.splitlines()
    expect.equal([path for path in tracked if path.startswith(("infra/bootstrap/", ".github/workflows/deploy.yml"))], [])
    this_file = str(Path(__file__).relative_to(REPO_ROOT))
    for term in STATE_BUCKET_TERMS:
        found = run_command("git", ["grep", "-l", "--fixed-strings", term], cwd=REPO_ROOT).stdout.splitlines()
        expect.equal([path for path in found if path not in (*HISTORY, this_file)], [], f"{term} is still referenced")


def test_every_terraform_script_selects_the_environment_workspace() -> None:
    # Commands that read or write state; terraform test and validate use their own temporary state.
    state_commands = r"terraform -chdir=[^ ]+ (output|plan|apply|state|show|import)"
    callers = run_command("git", ["grep", "-l", "-E", state_commands, "--", "*.sh"], cwd=REPO_ROOT, check=True).stdout.splitlines()
    for path in callers:
        script = (REPO_ROOT / path).read_text(encoding="utf-8")
        expect.equal("select_environment_workspace" in script, True, f"{path} runs Terraform without selecting the environment workspace")
    expect.equal(run_command("git", ["grep", "-l", "require_selected_backend", "--", "*.sh"], cwd=REPO_ROOT).stdout, "")


def test_destroy_apply_removes_the_local_state_once_it_is_empty() -> None:
    script = (REPO_ROOT / "scripts" / "infrastructure" / "teardown.sh").read_text(encoding="utf-8")
    destroy_block = script.split("  destroy-apply)", maxsplit=1)[1].split(";;", maxsplit=1)[0]

    expect.is_in("remove_local_state", destroy_block)
    function = script.split("remove_local_state() {", maxsplit=1)[1].split("\n}\n", maxsplit=1)[0]
    expect.is_in("state list", function)
