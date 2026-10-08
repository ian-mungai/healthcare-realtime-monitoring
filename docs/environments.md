---
title: "Environments"
description: "Select an environment file and preserve account and backend isolation."
last_updated: 2026-10-08
audience: [developer, operator]
---

# Environments

For developers and operators: select an environment file and preserve account and backend isolation.

## Terminology

- **AWS**: Amazon Web Services.
- **E2E**: end-to-end.
- **IAM**: Identity and Access Management.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<ENVIRONMENT>`: environment for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or AWS commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Scope

The project defines two deployment environments, each assigned to its own Amazon Web Services (AWS) account:

| Environment | `DEPLOYMENT_ENVIRONMENT` | Environment file | Purpose |
| --- | --- | --- | --- |
| Development | `development` (default when unset) | `.env` | Demos, end-to-end (E2E) runs and changes under test; torn down after each demo |
| Production | `production` | `.env.production` | The reviewed release deployment |

Separate accounts keep the environments apart without renaming resources: the Terraform resource names are fixed per project, so two environments in one account would collide. Each account has its own webhook secret and Identity and Access Management (IAM) policies. Each environment keeps its local Terraform state in its own workspace. Defining production configuration does not prove a production deployment exists.

## Select an Environment

Every script reads the environment file named by `PROJECT_ENV_FILE` or `.env` when it is unset. Both files are ignored by Git. Select production for a whole shell session:

1. Run the following command block:

   ```zsh
   export PROJECT_ENV_FILE=.env.production
   set -a
   source "$PROJECT_ENV_FILE"
   set +a
   ```

   The production file holds the production account's `AWS_PROFILE`, `AWS_ACCOUNT_ID`, `DATA_BUCKET_NAME` and alert address, plus:

2. Configure the following settings:

   ```dotenv
   DEPLOYMENT_ENVIRONMENT=production
   FHIR_RESOURCE_MAP_FILE=scripts/synthea_loader/state/production/fhir_resource_map.json
   ```

   `FHIR_RESOURCE_MAP_FILE` keeps each environment's HAPI patient IDs apart, because every HAPI server assigns its own IDs.

## Safeguards

- `render_project_config.sh` renders the ignored Terraform inputs from the selected file only.
- `infra/` keeps each environment's local state in its own Terraform workspace: `default` for development (`infra/terraform.tfstate`) and `production` for production (`infra/terraform.tfstate.d/production/terraform.tfstate`).
- Every plan names the rendered variable file explicitly with `-var-file=deployment.auto.tfvars.json`, in the scripts and the documented commands.
- Saved plans carry the environment in their names, for example `tfplan-bootstrap-application-production`, so a plan from one environment is never applied in another.
- Before any plan, apply, teardown or demo command, the scripts select the workspace of the selected file's `DEPLOYMENT_ENVIRONMENT`. The end-to-end runs stop when another workspace is selected.
- `check_prerequisites.sh` fails when the signed-in AWS account differs from `AWS_ACCOUNT_ID` in the selected file.
- Teardown asks for `CONFIRM_TEARDOWN=delete-healthcare-realtime-<ENVIRONMENT>`, so deleting production needs its own confirmation.

## Create Production

1. Export `PROJECT_ENV_FILE=.env.production` for the whole session:

   ```zsh
   export PROJECT_ENV_FILE=.env.production
   ```

2. Complete the [first-deployment quickstart](quickstart.md) in the production account.
Verify success with the quickstart's convergence check.

Resources named with the environment, such as queues, alarms and dashboards, use `production` in the production account; other names are identical in both accounts.
