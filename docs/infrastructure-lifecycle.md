# Infrastructure Lifecycle

## Safety model

Normal deployments set `allow_destructive_teardown = false`. This keeps DynamoDB and RDS deletion protection enabled and prevents Terraform from deleting populated S3 buckets or ECR repositories.

The teardown workflow is deliberately two phase. The first reviewed apply disables protection. A second saved plan destroys resources. The separate Terraform state bucket is never a target of either application phase. Full account retirement is a third, separately authorized procedure.

## Persistent state bootstrap

For a fresh clone with no state bucket, follow the [first-deployment quickstart](quickstart.md). It is the canonical creation procedure. The persistent state bucket and application resources use the single `AWS_REGION` value, so a new regional deployment creates its state bucket in that region.

The bootstrap stack intentionally uses local state and protects its bucket with `prevent_destroy`. The `state-backup` action saves the ignored bootstrap state at `s3://<terraform-state-bucket>/<project-name>/terraform/bootstrap/terraform.tfstate`. If local state is lost, restore this protected backup instead of trying to create a duplicate bucket.

The main state object uses `s3://<terraform-state-bucket>/<project-name>/terraform/terraform.tfstate`, keeping this project's state below a project-specific folder and Terraform subfolder.

To move an existing main stack from another backend, run `main-migrate` instead of `main-init` and approve Terraform's state migration:

```zsh
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh main-migrate
```

## Controlled application teardown

Stop demo tasks. Allow every MWAA workflow run to finish or stop it from the AWS console, then wait until its worker tasks have exited. An active workflow can prevent Terraform from deleting the workflow and can leave a metered ECS task running after an interrupted destroy.

Export only approved synthetic evidence and decide whether database snapshots must be retained.

Load the AWS context and persistent state bucket from the ignored environment file:

```zsh
set -a
source .env
set +a
```

Create and inspect the protection-removal plan. For a complete portfolio teardown, the wrapper sets `openlineage_skip_final_snapshot=true`; change the workflow and use a unique snapshot identifier when retention is required.

```zsh
./scripts/infrastructure/teardown.sh prepare-plan
terraform -chdir=infra show -no-color tfplan-teardown-prepare
CONFIRM_TEARDOWN=delete-healthcare-realtime-development \
  ./scripts/infrastructure/teardown.sh prepare-apply
```

Preview application storage. The command refuses to operate when `TF_STATE_BUCKET` matches the data bucket. Executing cleanup removes every object version, delete marker and ECR image listed by the preview.

```zsh
./scripts/infrastructure/teardown.sh cleanup-preview
CONFIRM_TEARDOWN=delete-healthcare-realtime-development \
  ./scripts/infrastructure/teardown.sh cleanup-apply
```

Create the final destroy plan, review every deletion and apply only that saved plan:

```zsh
./scripts/infrastructure/teardown.sh destroy-plan
terraform -chdir=infra show -no-color tfplan-teardown-destroy
CONFIRM_TEARDOWN=delete-healthcare-realtime-development \
  ./scripts/infrastructure/teardown.sh destroy-apply
```

If a destroy apply stops after deleting some resources, do not reuse its saved plan. Correct the permission or active-workflow cause, run `destroy-plan` again and review the replacement plan. The wrapper rebuilds packages while deployment outputs are available. After a partial destroy removes those outputs, it verifies and reuses the existing local artifacts so Terraform can finish removing the remaining resources.

Confirm that no application resources remain before separately considering the webhook secret, GitHub environment, account policies, OIDC provider or retained RDS snapshots. Keep the Terraform state bucket for future recreation and audit history.

Verify the destroyed application state and, when the deployment identity has Resource Groups Tagging API read access, search for tagged resources that require review:

```zsh
test -z "$(terraform -chdir=infra state list)"
aws resourcegroupstaggingapi get-resources \
  --region "$AWS_REGION" \
  --tag-filters "Key=Project,Values=$PROJECT_NAME" \
  --query 'ResourceTagMappingList[].ResourceARN' \
  --output text
```

The second command may list retained external prerequisites. Review each result against [external-prerequisites.md](external-prerequisites.md); do not delete a shared OIDC provider, shared policy or protected state bucket merely to make the result empty. If `tag:GetResources` is not permitted, use the empty Terraform state plus the AWS Billing resource inventory and service consoles as the independent account-level check.

## Full account retirement

Routine teardown keeps the versioned state bucket so the deployment remains auditable and recreatable. Retire that bucket only when all environments that use it are destroyed, `terraform -chdir=infra state list` is empty and an approved private state archive has been retained or explicitly declined.

The tracked deployment policy intentionally excludes `s3:DeleteObjectVersion` and `s3:DeleteBucket` for the state bucket. An account owner must grant those two actions temporarily on the exact state bucket and its objects, then revoke them immediately after retirement. Do not broaden the routine project policy merely to make this one-time action convenient.

Preview every retained version and delete marker before approving deletion:

```zsh
test -z "$(terraform -chdir=infra state list)"
aws s3api list-object-versions \
  --bucket "$TF_STATE_BUCKET" \
  --query '{Versions: Versions[].{Key:Key,VersionId:VersionId}, DeleteMarkers: DeleteMarkers[].{Key:Key,VersionId:VersionId}}'
```

After account-owner approval, delete versioned objects in bounded batches. The loop stops immediately if S3 reports a failed deletion:

```zsh
DELETE_REQUEST="$(mktemp "${TMPDIR:-/tmp}/healthcare-state-delete.XXXXXX")"
DELETE_RESPONSE="$(mktemp "${TMPDIR:-/tmp}/healthcare-state-response.XXXXXX")"

while true; do
  aws s3api list-object-versions \
    --bucket "$TF_STATE_BUCKET" \
    --max-items 1000 \
    --output json |
    jq '{Objects: (((.Versions // []) + (.DeleteMarkers // [])) | map({Key, VersionId})), Quiet: true}' \
      > "$DELETE_REQUEST"

  test "$(jq '.Objects | length' "$DELETE_REQUEST")" -eq 0 && break
  aws s3api delete-objects \
    --bucket "$TF_STATE_BUCKET" \
    --delete "file://$DELETE_REQUEST" \
    --output json > "$DELETE_RESPONSE"
  jq -e '((.Errors // []) | length) == 0' "$DELETE_RESPONSE"
done

aws s3api delete-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION"
rm -f "$DELETE_REQUEST" "$DELETE_RESPONSE"
```

Remove the retired bucket resources from the ignored local bootstrap state so a later fresh deployment plans a new bucket instead of refreshing a deleted one:

```zsh
while IFS= read -r address; do
  terraform -chdir=infra/bootstrap state rm "$address"
done < <(terraform -chdir=infra/bootstrap state list)
```

Confirm the bucket returns `NoSuchBucket`, revoke the temporary deletion permission and retain the webhook secret only when that is the approved retirement scope. A new account or region must start with the [first-deployment quickstart](quickstart.md) and an empty backend.

## Recreation

Reuse the persistent state bucket with a new empty state key or remove the old main-state object only after preserving an approved backup. When the state bucket was fully retired, recreate it through the bootstrap stage. Then follow the [first-deployment quickstart](quickstart.md) from the application repository at the intended commit. Use [deployment stages and recovery](bootstrap.md) only when a stage is interrupted.

Bucket names are globally unique and may be unavailable after deletion. Use new names in the ignored configuration when AWS does not immediately release an old name. Recreate the webhook secret, image repositories and images, synthetic FHIR cohort, HAPI subscription, analytical tables and approved model in the documented order.

For a different AWS account, create a new state bucket with `infra/bootstrap` and initialize an empty backend. Never reuse main Terraform state that still binds resources to another account.
