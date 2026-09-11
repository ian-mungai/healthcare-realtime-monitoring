# Deployment Guide

## GitHub OIDC bootstrap

GitHub deployment uses short-lived AWS credentials. It does not store AWS access keys in GitHub.

Create the ignored Terraform inputs from the tracked example and set:

```hcl
enable_github_oidc            = true
github_repository             = "<github-owner>/<repository>"
github_oidc_subject_prefix    = "repo:<github-owner>@<owner-id>/<repository>@<repository-id>"
github_deployment_environment = "development"
github_deployment_policy_arns = [
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_apigateway_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_cloudformation_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_cloudwatch_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_dynamodb_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_ec2_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_ecr_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_ecs_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_elasticloadbalancing_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_firehose_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_glue_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_iam_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_kinesis_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_kms_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_lambda_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_logs_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_mwaa_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_rds_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_s3_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_sns_policy",
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_sqs_policy",
]
```

These are the project's existing service policies, attached directly to the deployment role. The list intentionally stays within the default quota of 20 managed policies per role and does not create a duplicate deployment policy.

Read the repository's OIDC subject configuration and copy its `sub_claim_prefix` into `github_oidc_subject_prefix`:

```zsh
gh api repos/<github-owner>/<repository>/actions/oidc/customization/sub
```

When `use_immutable_subject` is enabled, the prefix contains numeric owner and repository IDs. Using it prevents a renamed or recreated repository from inheriting deployment access. Leave the variable empty only when GitHub reports the default mutable subject without a custom prefix.

Bootstrap the identity once from an authenticated local shell:

```zsh
terraform -chdir=infra plan -var-file=development.tfvars -out=tfplan-oidc
terraform -chdir=infra apply tfplan-oidc
terraform -chdir=infra output -raw github_deployment_role_arn
```

The trust policy accepts only tokens issued for the configured repository and protected GitHub `development` environment. If the AWS account already contains the GitHub OIDC provider, import it into this state before applying rather than creating a duplicate.

## Protected GitHub environment

Create a GitHub environment named `development`, restrict it to `main`, and require approval for deployment. Configure these environment variables:

| Name | Value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | Terraform `github_deployment_role_arn` output |
| `AWS_REGION` | Target AWS region |
| `TF_STATE_BUCKET` | Existing private project data bucket |

Add one environment secret named `TERRAFORM_VARIABLES_JSON`. Its value is a JSON object containing the same private inputs as `infra/development.tfvars`. Never commit or print this value.

Run the **Deploy** workflow manually with `action=plan`. Review its Terraform output, then run it again with `action=apply`. The apply run creates a fresh saved plan, applies exactly that plan, and verifies convergence. Container image tags in the secret must already refer to immutable images published by the project build process.

## Shared OpenLineage collector

The managed collector runs Marquez on private ECS and PostgreSQL RDS resources. An internal load balancer is reachable only through an IAM-authorized API Gateway endpoint, so no custom domain or public Marquez port is required. S3 remains the fallback when the collector is disabled.

Bootstrap the ECR repository while the collector remains disabled:

```zsh
export AWS_PROFILE="${AWS_PROFILE:-healthcare_realtime}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

terraform -chdir=infra plan \
  -var-file=development.tfvars \
  -target=module.openlineage_collector.aws_ecr_repository.marquez \
  -target=module.openlineage_collector.aws_ecr_lifecycle_policy.marquez \
  -out=tfplan-openlineage-ecr
terraform -chdir=infra apply tfplan-openlineage-ecr
```

Build and push the pinned Marquez image:

```zsh
export MARQUEZ_REPOSITORY_URL="$(terraform -chdir=infra output -raw openlineage_collector_ecr_repository_url)"
export MARQUEZ_IMAGE_TAG="sha-$(git rev-parse --short=12 HEAD)"

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "${MARQUEZ_REPOSITORY_URL%%/*}"

docker buildx build \
  --platform linux/amd64 \
  --file deploy/marquez/Dockerfile \
  --tag "${MARQUEZ_REPOSITORY_URL}:${MARQUEZ_IMAGE_TAG}" \
  --push \
  deploy/marquez
```

Enable the managed collector in the ignored Terraform inputs:

```hcl
enable_openlineage_collector        = true
openlineage_collector_image_tag     = "sha-<commit>"
openlineage_collector_desired_count = 1
openlineage_collector_url           = ""
```

Update the protected GitHub `TERRAFORM_VARIABLES_JSON` secret with the same values before using the Deploy workflow. Then create and review a full Terraform plan. The plan creates Marquez ECS, encrypted RDS, an internal load balancer, and the IAM-authorized API route; it also updates Glue, MWAA, dbt, and Soda with the collector URL and route-specific `execute-api:Invoke` permission.

After apply, run the analytical workflow. Confirm the collector has namespaces and jobs using the project's SigV4 session:

```zsh
export OPENLINEAGE_URL="$(terraform -chdir=infra output -raw openlineage_collector_url)"

.venv/bin/python - <<'PY'
import os
from urllib.parse import urlparse

from lineage.openlineage.client import build_sigv4_session, execute_api_region

url = os.environ["OPENLINEAGE_URL"].rstrip("/")
region = execute_api_region(urlparse(url).hostname)
if region is None:
    raise SystemExit("Expected the managed API Gateway collector URL")
response = build_sigv4_session(region).get(f"{url}/api/v1/namespaces", timeout=10)
response.raise_for_status()
print(response.json())
PY
```

For cost-controlled shutdown, set `openlineage_collector_desired_count = 0` and apply. Stop the Marquez RDS instance from AWS when the analytical workflow is not being demonstrated; AWS automatically restarts a stopped RDS instance after seven days. Restore the database and desired count before running the pipeline.

To use an externally managed collector instead, leave `enable_openlineage_collector = false` and set `openlineage_collector_url` to its HTTPS base URL. External collectors are not automatically assigned AWS SigV4 authentication.
