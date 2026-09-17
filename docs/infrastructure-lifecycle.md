# Infrastructure Lifecycle

## Safety model

Normal deployments set `allow_destructive_teardown = false`. This keeps DynamoDB and RDS deletion protection enabled and prevents Terraform from deleting populated S3 buckets or ECR repositories.

The teardown workflow is deliberately two phase. The first reviewed apply disables protection. A second saved plan destroys resources. The separate Terraform state bucket is never a target of either phase.

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

Stop demo tasks and allow any running MWAA workflow to finish. Export only approved synthetic evidence and decide whether database snapshots must be retained.

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

Confirm that no application resources remain before separately considering the webhook secret, GitHub environment, account policies, OIDC provider or retained RDS snapshots. Keep the Terraform state bucket for future recreation and audit history.

Verify the destroyed application state and search for tagged resources that require review:

```zsh
test -z "$(terraform -chdir=infra state list)"
aws resourcegroupstaggingapi get-resources \
  --region "$AWS_REGION" \
  --tag-filters "Key=Project,Values=$PROJECT_NAME" \
  --query 'ResourceTagMappingList[].ResourceARN' \
  --output text
```

The second command may list retained external prerequisites. Review each result against [external-prerequisites.md](external-prerequisites.md); do not delete a shared OIDC provider, shared policy or protected state bucket merely to make the result empty.

## Recreation

Reuse the persistent state bucket with a new empty state key or remove the old main-state object only after preserving an approved backup. Then follow the [first-deployment quickstart](quickstart.md) from the application repository at the intended commit. Use [deployment stages and recovery](bootstrap.md) only when a stage is interrupted.

Bucket names are globally unique and may be unavailable after deletion. Use new names in the ignored configuration when AWS does not immediately release an old name. Recreate the webhook secret, image repositories and images, synthetic FHIR cohort, HAPI subscription, analytical tables and approved model in the documented order.

For a different AWS account, create a new state bucket with `infra/bootstrap` and initialize an empty backend. Never reuse main Terraform state that still binds resources to another account.
