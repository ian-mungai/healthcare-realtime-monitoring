# Deployment Guide

## GitHub OIDC bootstrap

GitHub deployment uses short-lived AWS credentials. It does not store AWS access keys in GitHub.

Create the ignored Terraform inputs from the tracked example and set:

```hcl
enable_github_oidc            = true
github_repository             = "<github-owner>/<repository>"
github_deployment_environment = "development"
github_deployment_policy_arns = [
  "arn:aws:iam::<aws-account-id>:policy/healthcare_realtime_deployment",
]
```

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

Set the collector base URL in the ignored Terraform inputs:

```hcl
openlineage_collector_url = "https://<openlineage-collector>"
```

Glue, Athena, dbt, Soda, and Great Expectations then emit to the shared HTTP endpoint `api/v1/lineage`. If the URL is empty, the project retains its existing durable S3 transport. Use HTTPS for a remote collector; plain HTTP is intended only for an isolated local collector.
