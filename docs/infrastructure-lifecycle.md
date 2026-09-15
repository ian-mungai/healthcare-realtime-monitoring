# Infrastructure Lifecycle

## Safety model

Normal deployments set `allow_destructive_teardown = false`. This keeps DynamoDB and RDS deletion protection enabled and prevents Terraform from deleting populated S3 buckets or ECR repositories.

The teardown workflow is deliberately two phase. The first reviewed apply disables protection. A second saved plan destroys resources. The separate Terraform state bucket is never a target of either phase.

## Persistent state bootstrap

Create the ignored bootstrap inputs, review the state-bucket plan, and apply it:

Replace the placeholders in `infra/bootstrap/terraform.tfvars` before running the following commands.

```zsh
cp infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars
./scripts/infrastructure/bootstrap.sh state-plan
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh state-apply
./scripts/infrastructure/bootstrap.sh state-backup
./scripts/infrastructure/bootstrap.sh main-init
```

The bootstrap stack intentionally uses local state and protects its bucket with `prevent_destroy`. The `state-backup` action saves the ignored bootstrap state at `s3://<terraform-state-bucket>/healthcare-realtime-monitoring/terraform/bootstrap/terraform.tfstate`. If local state is lost, restore this protected backup instead of trying to create a duplicate bucket.

The main state object uses `s3://<terraform-state-bucket>/healthcare-realtime-monitoring/terraform/terraform.tfstate`, keeping this project's state below a project-specific folder and Terraform subfolder.

To move an existing main stack from another backend, run `main-migrate` instead of `main-init` and approve Terraform's state migration:

```zsh
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh main-migrate
```

## Controlled application teardown

Stop demo tasks and allow any running MWAA workflow to finish. Export only approved synthetic evidence and decide whether database snapshots must be retained.

Set the AWS context and the persistent state bucket:

```zsh
export AWS_PROFILE="<aws-profile>"
export AWS_REGION="<aws-region>"
export AWS_DEFAULT_REGION="$AWS_REGION"
export TF_STATE_BUCKET="<terraform-state-bucket>"
```

Create and inspect the protection-removal plan. For a complete portfolio teardown, the wrapper sets `openlineage_skip_final_snapshot=true`; change the workflow and use a unique snapshot identifier when retention is required.

```zsh
./scripts/infrastructure/teardown.sh prepare-plan
terraform -chdir=infra show -no-color tfplan-teardown-prepare
CONFIRM_TEARDOWN=delete-healthcare-realtime-development \
  ./scripts/infrastructure/teardown.sh prepare-apply
```

Preview application storage. The command refuses to operate when `TF_STATE_BUCKET` matches the data bucket. Executing cleanup removes every object version, delete marker, and ECR image listed by the preview.

```zsh
./scripts/infrastructure/teardown.sh cleanup-preview
CONFIRM_TEARDOWN=delete-healthcare-realtime-development \
  ./scripts/infrastructure/teardown.sh cleanup-apply
```

Create the final destroy plan, review every deletion, and apply only that saved plan:

```zsh
./scripts/infrastructure/teardown.sh destroy-plan
terraform -chdir=infra show -no-color tfplan-teardown-destroy
CONFIRM_TEARDOWN=delete-healthcare-realtime-development \
  ./scripts/infrastructure/teardown.sh destroy-apply
```

Confirm that no application resources remain before separately considering the webhook secret, GitHub environment, account policies, OIDC provider, or retained RDS snapshots. Keep the Terraform state bucket for future recreation and audit history.

## Recreation

Reuse the persistent state bucket with a new empty state key or remove the old main-state object only after preserving an approved backup. Then follow [bootstrap.md](bootstrap.md) from the application repository at the intended commit.

Bucket names are globally unique and may be unavailable after deletion. Use new names in the ignored configuration when AWS does not immediately release an old name. Recreate the webhook secret, image repositories and images, synthetic FHIR cohort, HAPI subscription, analytical tables, and approved model in the documented order.
