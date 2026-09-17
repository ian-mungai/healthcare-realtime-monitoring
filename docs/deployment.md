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
./scripts/infrastructure/render_project_config.sh --check
terraform -chdir=infra plan -out=tfplan-oidc
terraform -chdir=infra apply tfplan-oidc
terraform -chdir=infra output -raw github_deployment_role_arn
```

The trust policy accepts only tokens issued for the configured repository and protected GitHub deployment environment. If the AWS account already contains the GitHub OIDC provider, import it into this state before applying rather than creating a duplicate.

## Protected GitHub environment

Create the protected GitHub environment named by `github_deployment_environment`, restrict it to `main` and require approval for deployment. Configure this non-sensitive environment variable:

| Name | Value |
| --- | --- |
| `AWS_REGION` | Target AWS region |

Add three environment secrets:

| Name | Value |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | Terraform `github_deployment_role_arn` output |
| `TF_STATE_BUCKET` | Dedicated persistent state bucket created by `infra/bootstrap` |
| `TF_STATE_PREFIX` | `<project-name>/terraform` |

Synchronize the generated private configuration from `.env` into encrypted, versioned AWS storage:

```zsh
./scripts/infrastructure/sync_deployment_config.sh
```

The object is stored under `$TF_STATE_PREFIX/config/` in the persistent state bucket. `TF_STATE_PREFIX` must equal `<project-name>/terraform`; the synchronization and prerequisite scripts enforce that relationship. The Deploy workflow authenticates through GitHub OIDC before retrieving it and uses the single `AWS_REGION` environment variable for both Terraform state and application resources. The bucket and prefix remain protected secrets because this public portfolio treats deployment identifiers as private; redacted plan diagnostics preserve useful errors without exposing those identifiers. Do not create a bulk `TERRAFORM_VARIABLES_JSON` GitHub secret and do not expose account-specific identifiers as GitHub variables.

Run a full local Terraform plan to review resource details without publishing private identifiers. Then run the **Deploy** workflow manually, select the protected environment and choose `action=plan` for remote verification. The workflow publishes a value-free table of resource addresses and actions to the job summary and prints redacted diagnostics if planning fails. Run it again with `action=apply` after approval. The apply run creates a fresh saved plan, applies exactly that plan and verifies convergence. Container image tags in the private AWS configuration must already refer to immutable images published by the project build process.

## Shared OpenLineage collector

The managed collector runs Marquez on private ECS and PostgreSQL RDS resources. An internal load balancer is reachable only through an IAM-authorized API Gateway endpoint, so no custom domain or public Marquez port is required. S3 remains the fallback when the collector is disabled.

Bootstrap the ECR repository while the collector remains disabled:

```zsh
set -a
source .env
set +a

terraform -chdir=infra plan \
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
  --provenance=false \
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

Run `./scripts/infrastructure/sync_deployment_config.sh` after updating the ignored Terraform inputs, then create and review a full Terraform plan. The plan creates Marquez ECS, encrypted RDS, an internal load balancer and the IAM-authorized API route; it also updates Glue, MWAA, dbt and Soda with the collector URL and route-specific `execute-api:Invoke` permission.

After apply, run the analytical workflow. Confirm the collector has namespaces and jobs using the project's SigV4 session:

```zsh
export OPENLINEAGE_URL="$(terraform -chdir=infra output -raw openlineage_collector_url)"

.venv/bin/python - <<'PY'
import os

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.httpsession import URLLib3Session

url = f'{os.environ["OPENLINEAGE_URL"].rstrip("/")}/api/v1/namespaces'
region = os.environ["AWS_REGION"]
credentials = boto3.Session().get_credentials()
if credentials is None:
    raise SystemExit("AWS credentials are required")
request = AWSRequest(method="GET", url=url)
SigV4Auth(credentials.get_frozen_credentials(), "execute-api", region).add_auth(request)
response = URLLib3Session().send(request.prepare())
if response.status_code >= 400:
    raise SystemExit(f"Collector returned HTTP {response.status_code}")
print(response.content.decode())
PY
```

For cost-controlled shutdown, set `openlineage_collector_desired_count = 0` and apply. Stop the Marquez RDS instance from AWS when the analytical workflow is not being demonstrated; AWS automatically restarts a stopped RDS instance after seven days. Restore the database and desired count before running the pipeline.

To use an externally managed collector instead, leave `enable_openlineage_collector = false` and set `openlineage_collector_url` to its HTTPS base URL. Every non-local remote collector request is SigV4-signed for `execute-api`; use a local endpoint for unsigned development transport.
