from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_deployment_workflow_retrieves_private_config_after_oidc() -> None:
    workflow = (REPO_ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "TERRAFORM_VARIABLES_JSON" not in workflow
    assert "${{ secrets.AWS_DEPLOY_ROLE_ARN }}" in workflow
    assert "${{ secrets.TF_STATE_BUCKET }}" in workflow
    assert "${{ secrets.TF_STATE_PREFIX }}" in workflow
    assert "${{ vars.AWS_DEPLOY_ROLE_ARN }}" not in workflow
    assert "${{ vars.TF_STATE_BUCKET }}" not in workflow
    assert "${{ vars.TF_STATE_PREFIX }}" not in workflow
    assert workflow.index("Configure temporary AWS credentials") < workflow.index("Retrieve private Terraform inputs")
    assert "aws s3api get-object" in workflow
    assert 'deployment_config_key="$TF_STATE_PREFIX/config/deployment.auto.tfvars.json"' in workflow


def test_deployment_workflow_publishes_value_free_plan_summary() -> None:
    workflow = (REPO_ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert 'cat "$RUNNER_TEMP/tfplan.txt"' not in workflow
    assert '>"$RUNNER_TEMP/tfplan.log" 2>&1' in workflow
    assert "terraform -chdir=infra show -json tfplan-deploy" in workflow
    assert "summarize_terraform_plan.py" in workflow
    assert 'tee -a "$GITHUB_STEP_SUMMARY"' in workflow
    assert "sanitize_terraform_output.py" in workflow
    assert "--values-json infra/deployment.auto.tfvars.json" in workflow


def test_sync_script_uses_shared_prefix_and_bucket_encryption() -> None:
    script = (REPO_ROOT / "scripts/infrastructure/sync_deployment_config.sh").read_text(encoding="utf-8")

    assert "mktemp" in script
    assert "trap 'rm -f \"$TEMP_CONFIG\"' EXIT" in script
    assert "--server-side-encryption" not in script
    assert 'CONFIG_KEY="$TF_STATE_PREFIX/config/deployment.auto.tfvars.json"' in script
    assert 'EXPECTED_STATE_PREFIX="$PROJECT_NAME/terraform"' in script
    assert 'PYTHON_BIN="$(command -v python3)"' in script
