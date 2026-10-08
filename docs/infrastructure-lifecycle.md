---
title: "Infrastructure Lifecycle"
description: "Keep Terraform state locally during a deployment, tear down application resources and remove the state."
last_updated: 2026-10-08
audience: [developer, operator]
---

# Infrastructure Lifecycle

For developers and operators: keep Terraform state locally during a deployment, tear down application resources and remove the state.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Safety Model](#safety-model)
- [Local Terraform State](#local-terraform-state)
- [Controlled Application Teardown](#controlled-application-teardown)
- [Recreation](#recreation)

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **MWAA**: Managed Workflows for Apache Airflow.
- **RDS**: Relational Database Service.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<PROJECT_NAME>`: project name for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Safety Model

Normal deployments set `allow_destructive_teardown = false`. This keeps DynamoDB and Relational Database Service (RDS) deletion protection enabled and prevents Terraform from deleting populated S3 buckets or Elastic Container Registry (ECR) repositories.

The teardown workflow is deliberately two phase. The first reviewed apply disables protection. A second saved plan destroys resources. Deployments are temporary, so no Terraform state is kept after a teardown: the destroy apply removes the local state once it lists no resource.

## Local Terraform State

Terraform keeps the application state in a local file in `infra/`, ignored by Git. There is no state bucket, no bootstrap stack and no copy of the state in AWS: a deployment lasts for one demo and is torn down after it, so nothing needs to be kept between deployments.

- `./scripts/infrastructure/bootstrap.sh init` initializes `infra/` and selects the environment's workspace. Development uses the `default` workspace, whose state is `infra/terraform.tfstate`; any other `DEPLOYMENT_ENVIRONMENT` gets its own workspace and `infra/terraform.tfstate.d/<ENVIRONMENT>/terraform.tfstate`, so environments in separate accounts never share a state file.
- Every script that reads or changes state selects the environment's workspace first. The end-to-end runs stop when another workspace is selected.
- Deploy and tear down from the same checkout: the state exists only there. Losing it before teardown means removing the resources by hand, so do not delete `infra/terraform.tfstate` while a deployment is up.
- `teardown.sh destroy-apply` removes the workspace's state file, its backups and the saved plans, which hold a copy of the state, once `terraform state list` is empty.

## Controlled Application Teardown

Prerequisites:

- Stopped demo tasks and end-to-end runs.
- No leftover `healthcare_realtime_e2e_replay_*` policy. Remove an owned leftover through the [operations runbook](operations-runbook.md#end-to-end-scenarios) after exact approval. Terraform does not manage that policy.
- Finished or explicitly stopped Managed Workflows for Apache Airflow (MWAA) runs with all worker tasks exited. An active workflow can block deletion and leave a metered Elastic Container Service (ECS) task after an interrupted destroy.
- An approved evidence-export scope and an explicit database-snapshot retention decision.
- Separate approval for each exact protection-removal apply, storage cleanup and destroy apply.

1. Load the AWS context from the ignored environment file:

   ```zsh
   set -a
   source "${PROJECT_ENV_FILE:-.env}"
   set +a
   ```

   Create and inspect the protection-removal plan. For a complete portfolio teardown, the wrapper sets `openlineage_skip_final_snapshot=true`; change the workflow and use a unique snapshot identifier when retention is required.

2. Run the following command block:

   ```zsh
   ./scripts/infrastructure/teardown.sh prepare-plan
   terraform -chdir=infra show -no-color "tfplan-teardown-prepare-${DEPLOYMENT_ENVIRONMENT:-development}"
   ```

   Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

3. Apply only the reviewed and approved action:

   ```zsh
   CONFIRM_TEARDOWN="delete-healthcare-realtime-${DEPLOYMENT_ENVIRONMENT:-development}" \
     ./scripts/infrastructure/teardown.sh prepare-apply
   ```

   Preview application storage. Executing cleanup removes every object version, delete marker and ECR image listed by the preview.

4. Run the following command block:

   ```zsh
   ./scripts/infrastructure/teardown.sh cleanup-preview
   ```

   Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

5. Apply only the reviewed and approved action:

   ```zsh
   CONFIRM_TEARDOWN="delete-healthcare-realtime-${DEPLOYMENT_ENVIRONMENT:-development}" \
     ./scripts/infrastructure/teardown.sh cleanup-apply
   ```

   Create the final destroy plan, review every deletion and apply only that saved plan:

6. Run the following command block:

   ```zsh
   ./scripts/infrastructure/teardown.sh destroy-plan
   terraform -chdir=infra show -no-color "tfplan-teardown-destroy-${DEPLOYMENT_ENVIRONMENT:-development}"
   ```

   Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

7. Apply only the reviewed and approved action:

   ```zsh
   CONFIRM_TEARDOWN="delete-healthcare-realtime-${DEPLOYMENT_ENVIRONMENT:-development}" \
     ./scripts/infrastructure/teardown.sh destroy-apply
   ```

   If a destroy apply stops after deleting some resources, do not reuse its saved plan. Correct the permission or active-workflow cause, run `destroy-plan` again and review the replacement plan. The wrapper rebuilds packages while deployment outputs are available. After a partial destroy removes those outputs, it verifies and reuses the existing local artifacts so Terraform can finish removing the remaining resources.

   After the destroy, the wrapper checks that `terraform state list` is empty and only then removes the local state file, its backups and the saved plans. It stops and keeps the state when any resource remains. Confirm that no application resources remain before separately considering the webhook secret, the Grafana admin secret, account policies or retained RDS snapshots.

   When the deployment identity has Resource Groups Tagging application programming interface (API) read access, search for tagged resources that require review:

8. Run the following command block:

   ```zsh
   aws resourcegroupstaggingapi get-resources \
     --region "$AWS_REGION" \
     --tag-filters "Key=Project,Values=$PROJECT_NAME" \
     --query 'ResourceTagMappingList[].ResourceARN' \
     --output text
   ```

   The command may list retained external prerequisites. Review each result against [external-prerequisites.md](external-prerequisites.md); do not delete a shared policy merely to make the result empty. If `tag:GetResources` is not permitted, use the destroy output plus the AWS Billing resource inventory and service consoles as the independent account-level check. Log groups that AWS creates on first write, such as `/aws/lambda/healthcare_realtime_*`, `/aws/ecs/containerinsights/healthcare-realtime-*` and `/aws/mwaa-serverless/healthcare_realtime_*`, are not in Terraform state; review and delete them separately after approval.

## Recreation

Every deployment starts with empty local state. Follow the [first-deployment quickstart](quickstart.md) from the application repository at the intended commit. Use [deployment stages and recovery](bootstrap.md) only when a stage is interrupted.

Bucket names are globally unique and may be unavailable after deletion. Use new names in the ignored configuration when AWS does not immediately release an old name. Recreate the webhook secret, image repositories and images, synthetic Fast Healthcare Interoperability Resources (FHIR) cohort, HAPI subscription, analytical tables and approved model in the documented order.

For a different AWS account, use that account's environment file with its own `DEPLOYMENT_ENVIRONMENT`, so its state lives in its own workspace. Never reuse a state file that still binds resources to another account.
