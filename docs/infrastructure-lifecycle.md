---
title: "Infrastructure Lifecycle"
description: "Create state, tear down application resources and preserve or retire protected backups."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Infrastructure Lifecycle

For developers and operators: create state, tear down application resources and preserve or retire protected backups.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Safety Model](#safety-model)
- [Persistent State Bootstrap](#persistent-state-bootstrap)
- [Controlled Application Teardown](#controlled-application-teardown)
- [Full Account Retirement](#full-account-retirement)
- [Recreation](#recreation)

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **MWAA**: Managed Workflows for Apache Airflow.
- **OIDC**: OpenID Connect.
- **RDS**: Relational Database Service.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<PROJECT_NAME>`: project name for the selected environment or example.
- `<TERRAFORM_STATE_BUCKET>`: terraform state bucket for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Safety Model

Normal deployments set `allow_destructive_teardown = false`. This keeps DynamoDB and Relational Database Service (RDS) deletion protection enabled and prevents Terraform from deleting populated S3 buckets or Elastic Container Registry (ECR) repositories.

The teardown workflow is deliberately two phase. The first reviewed apply disables protection. A second saved plan destroys resources. The separate Terraform state bucket is never a target of either application phase. Full account retirement is a third, separately authorized procedure.

## Persistent State Bootstrap

For a fresh clone with no state bucket, follow the [first-deployment quickstart](quickstart.md). It is the canonical creation procedure. The persistent state bucket and application resources use the single `AWS_REGION` value, so a new regional deployment creates its state bucket in that region.

The bootstrap stack intentionally uses local state and protects its bucket with `prevent_destroy`. The `state-backup` action saves the ignored bootstrap state at `s3://<TERRAFORM_STATE_BUCKET>/<PROJECT_NAME>/terraform/bootstrap/terraform.tfstate`. If local state is lost, restore this protected backup instead of trying to create a duplicate bucket.

The main state object uses `s3://<TERRAFORM_STATE_BUCKET>/<PROJECT_NAME>/terraform/terraform.tfstate`, keeping this project's state below a project-specific folder and Terraform subfolder.

Migration prerequisites:

- Authorization for the exact state transfer.
- A verified source backend, destination state bucket and protected backup.

1. Migrate the existing main stack with `main-migrate` instead of `main-init`. Review Terraform's interactive prompt and accept only the intended state transfer:

   ```zsh
   CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
     ./scripts/infrastructure/bootstrap.sh main-migrate
   ```

2. Verify the destination main-state object exists and Terraform lists the expected resources. Keep the protected backup until recovery is independently verified.

## Controlled Application Teardown

Prerequisites:

- Stopped demo tasks and end-to-end runs.
- No leftover `healthcare_realtime_e2e_replay_*` policy. Remove an owned leftover through the [operations runbook](operations-runbook.md#end-to-end-scenarios) after exact approval. Terraform does not manage that policy.
- Finished or explicitly stopped Managed Workflows for Apache Airflow (MWAA) runs with all worker tasks exited. An active workflow can block deletion and leave a metered Elastic Container Service (ECS) task after an interrupted destroy.
- An approved evidence-export scope and an explicit database-snapshot retention decision.
- Separate approval for each exact protection-removal apply, storage cleanup and destroy apply.

1. Load the AWS context and persistent state bucket from the ignored environment file:

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

   Preview application storage. The command refuses to operate when `TF_STATE_BUCKET` matches the data bucket. Executing cleanup removes every object version, delete marker and ECR image listed by the preview.

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

   Confirm that no application resources remain before separately considering the webhook secret, the Grafana admin secret, GitHub environment, account policies, OpenID Connect (OIDC) provider or retained RDS snapshots. Keep the Terraform state bucket for future recreation and audit history.

   Verify the destroyed application state and, when the deployment identity has Resource Groups Tagging application programming interface (API) read access, search for tagged resources that require review:

8. Run the following command block:

   ```zsh
   (
   STATE_LIST="$(terraform -chdir=infra state list)" || exit 1
   test -z "$STATE_LIST" || exit 1
   aws resourcegroupstaggingapi get-resources \
     --region "$AWS_REGION" \
     --tag-filters "Key=Project,Values=$PROJECT_NAME" \
     --query 'ResourceTagMappingList[].ResourceARN' \
     --output text
   )
   ```

   The second command may list retained external prerequisites. Review each result against [external-prerequisites.md](external-prerequisites.md); do not delete a shared OIDC provider, shared policy or protected state bucket merely to make the result empty. If `tag:GetResources` is not permitted, use the empty Terraform state plus the AWS Billing resource inventory and service consoles as the independent account-level check.

## Full Account Retirement

Routine teardown keeps the versioned state bucket so the deployment remains auditable and recreatable. Retire that bucket only when all environments that use it are destroyed, `terraform -chdir=infra state list` is empty and an approved private state archive has been retained or explicitly declined.

The tracked deployment policy intentionally excludes `s3:DeleteObjectVersion` and `s3:DeleteBucket` for the state bucket. An account owner must grant those two actions temporarily on the exact state bucket and its objects, then revoke them immediately after retirement. Do not broaden the routine project policy merely to make this one-time action convenient.

Prerequisites:

- Destroyed environments with verified empty application state.
- An approved private state archive retained or explicitly declined.
- Account-owner approval for the exact version inventory, bucket deletion and local bootstrap-state removal.
- Temporary deletion permissions restricted to that bucket and its objects, with revocation included in the approved scope.

1. Preview every retained version and delete marker:

   ```zsh
   (
   STATE_LIST="$(terraform -chdir=infra state list)" || exit 1
   test -z "$STATE_LIST" || exit 1
   aws s3api list-object-versions \
     --bucket "$TF_STATE_BUCKET" \
     --query '{Versions: Versions[].{Key:Key,VersionId:VersionId}, DeleteMarkers: DeleteMarkers[].{Key:Key,VersionId:VersionId}}'
   )
   ```

   Review that exact inventory with the account owner before deletion.

2. Delete only the approved versioned objects and bucket. Stop if the reviewed inventory changes. The subshell uses bounded batches, stops on listing, parsing or deletion failure and retains private request/response files on failure. Successful deletion removes those temporary files. The bucket is deleted only after an empty version inventory:

   ```zsh
   (
   set -o pipefail
   DELETE_REQUEST="$(mktemp "${TMPDIR:-/tmp}/healthcare-state-delete.XXXXXX")"
   DELETE_RESPONSE="$(mktemp "${TMPDIR:-/tmp}/healthcare-state-response.XXXXXX")"

   while true; do
     aws s3api list-object-versions \
       --bucket "$TF_STATE_BUCKET" \
       --max-items 1000 \
       --output json |
       jq '{Objects: (((.Versions // []) + (.DeleteMarkers // [])) | map({Key, VersionId})), Quiet: true}' \
         > "$DELETE_REQUEST" || exit 1

     test "$(jq '.Objects | length' "$DELETE_REQUEST")" -eq 0 && break
     aws s3api delete-objects \
       --bucket "$TF_STATE_BUCKET" \
       --delete "file://$DELETE_REQUEST" \
       --output json > "$DELETE_RESPONSE" || exit 1
     jq -e '((.Errors // []) | length) == 0' "$DELETE_RESPONSE" || exit 1
   done

   aws s3api delete-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION" || exit 1
   rm -f "$DELETE_REQUEST" "$DELETE_RESPONSE"
   )
   ```

   Remove the retired bucket resources from the ignored local bootstrap state so a later fresh deployment plans a new bucket instead of refreshing a deleted one:

3. Remove only the approved retired-bucket addresses from local bootstrap state. Verify the listed addresses belong to the retired bucket before running this command:

   ```zsh
   while IFS= read -r address; do
     terraform -chdir=infra/bootstrap state rm "$address"
   done < <(terraform -chdir=infra/bootstrap state list)
   ```

4. Confirm the bucket returns `NoSuchBucket` and local bootstrap state no longer lists its retired resources. Revoke the temporary deletion permission and verify its absence. Retain the webhook and Grafana admin secrets only when that is the approved retirement scope. A new account or region starts with the [first-deployment quickstart](quickstart.md) and an empty backend.

## Recreation

Reuse the persistent state bucket with a new empty state key or remove the old main-state object only after preserving an approved backup. When the state bucket was fully retired, recreate it through the bootstrap stage. Then follow the [first-deployment quickstart](quickstart.md) from the application repository at the intended commit. Use [deployment stages and recovery](bootstrap.md) only when a stage is interrupted.

Bucket names are globally unique and may be unavailable after deletion. Use new names in the ignored configuration when AWS does not immediately release an old name. Recreate the webhook secret, image repositories and images, synthetic Fast Healthcare Interoperability Resources (FHIR) cohort, HAPI subscription, analytical tables and approved model in the documented order.

For a different AWS account, create a new state bucket with `infra/bootstrap` and initialize an empty backend. Never reuse main Terraform state that still binds resources to another account.
