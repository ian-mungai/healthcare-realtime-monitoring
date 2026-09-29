from pathlib import Path

from testkit import expect

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_deployment_workflow_retrieves_private_config_after_oidc() -> None:
    workflow = (REPO_ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    expect.not_in("TERRAFORM_VARIABLES_JSON", workflow)
    expect.is_in("${{ secrets.AWS_DEPLOY_ROLE_ARN }}", workflow)
    expect.is_in("${{ secrets.TF_STATE_BUCKET }}", workflow)
    expect.is_in("${{ secrets.TF_STATE_PREFIX }}", workflow)
    expect.not_in("TF_STATE_REGION", workflow)
    expect.not_in("${{ vars.AWS_DEPLOY_ROLE_ARN }}", workflow)
    expect.not_in("${{ vars.TF_STATE_BUCKET }}", workflow)
    expect.not_in("${{ vars.TF_STATE_PREFIX }}", workflow)
    if not (workflow.index("Configure temporary AWS credentials") < workflow.index("Retrieve private Terraform inputs")):
        expect.fail('expected: workflow.index("Configure temporary AWS credentials") < workflow.index("Retrieve private Terraform inputs")')
    if not (workflow.index("Configure temporary AWS credentials") < workflow.index("Validate authenticated deployment access")):
        expect.fail('expected: workflow.index("Configure temporary AWS credentials") < workflow.index("Validate authenticated deployment access")')
    expect.is_in("aws sts get-caller-identity --query Arn --output text", workflow)
    expect.is_in('aws s3api head-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION"', workflow)
    expect.is_in("aws s3api get-object", workflow)
    expect.is_in('deployment_config_key="$TF_STATE_PREFIX/config/deployment.auto.tfvars.json"', workflow)
    expect.is_in('test "$TF_STATE_PREFIX" = "$(jq -r \'.project_name\' infra/deployment.auto.tfvars.json)/terraform"', workflow)


def test_deployment_workflow_publishes_value_free_plan_summary() -> None:
    workflow = (REPO_ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    expect.not_in('cat "$RUNNER_TEMP/tfplan.txt"', workflow)
    expect.is_in('>"$RUNNER_TEMP/tfplan.log" 2>&1', workflow)
    expect.is_in("terraform -chdir=infra show -json tfplan-deploy", workflow)
    expect.is_in("summarize_terraform_plan.py", workflow)
    expect.is_in('tee -a "$GITHUB_STEP_SUMMARY"', workflow)
    expect.is_in("sanitize_terraform_output.py", workflow)
    expect.is_in("--values-json infra/deployment.auto.tfvars.json", workflow)


def test_sync_script_uses_shared_prefix_and_bucket_encryption() -> None:
    script = (REPO_ROOT / "scripts/infrastructure/sync_deployment_config.sh").read_text(encoding="utf-8")

    expect.is_in("render_project_config.sh", script)
    expect.is_in('TFVARS_FILE="$REPO_ROOT/infra/deployment.auto.tfvars.json"', script)
    expect.not_in("--server-side-encryption", script)
    expect.is_in('CONFIG_KEY="$TF_STATE_PREFIX/config/deployment.auto.tfvars.json"', script)
    expect.is_in('EXPECTED_STATE_PREFIX="$PROJECT_NAME/terraform"', script)
    expect.is_in('--region "$AWS_REGION"', script)


def test_published_images_use_ecr_scannable_manifests() -> None:
    script = (REPO_ROOT / "scripts/infrastructure/push_images.sh").read_text(encoding="utf-8")

    expect.equal(script.count("docker buildx build"), 4)
    expect.equal(script.count("--provenance=false"), 4)
    expect.is_in("update_env_value", script)
    expect.is_in("VITALS_SIMULATOR_IMAGE_TAG DBT_IMAGE_TAG SODA_IMAGE_TAG OPENLINEAGE_COLLECTOR_IMAGE_TAG", script)
    expect.is_in('"$REPO_ROOT/scripts/infrastructure/render_project_config.sh" --env-file "$ENV_FILE"', script)
