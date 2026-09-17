# First Deployment

## 1. Prepare the clone

From the repository root, install the pinned Python dependencies and create ignored local configuration:

```zsh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_dev.txt
cp .env.example .env
```

Use the root requirements file as the single local dependency entry point. It includes the pinned Airflow workflow-generator requirements and keeps Apache Airflow 3.3.1 compatible with SQLAlchemy 2.0.50 in the project virtual environment.

Replace every placeholder in `.env`, enter the target region once as `AWS_REGION`, use globally unique names for the state and application-data buckets and render both Terraform inputs:

```zsh
./scripts/infrastructure/render_project_config.sh
```

Stable project defaults live in `config/deployment.defaults.json`. The generated Terraform JSON files are ignored and must not be edited directly. Terraform-created endpoints and resource identifiers come from Terraform outputs. `.env` is authoritative for deployment inputs, so stale shell exports cannot change generated configuration. Leave `ML_APPROVED_MODEL_VERSION` empty for the first deployment; this keeps MWAA in manual-only mode while the training dataset and first model are created. Never commit `.env` or generated configuration.

The documented local workflow requires a named AWS CLI profile in `AWS_PROFILE`. An SSO-backed profile is supported after `aws sso login --profile "$AWS_PROFILE"`.

Run the local and regional checks before creating resources:

```zsh
./scripts/infrastructure/check_prerequisites.sh local
.venv/bin/python scripts/infrastructure/check_region_readiness.py \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
```

Render and review every tracked customer-managed IAM policy, then apply them with the guarded policy command documented in the [first-deployment quickstart](quickstart.md). Policy publication does not attach permissions, so confirm the bootstrap identity receives every tracked service policy through the approved account group or role model. Use an approved bootstrap identity because Terraform cannot create the identity and permissions needed to start itself.

Create the persistent state bucket before initializing the application stack:

```zsh
./scripts/infrastructure/bootstrap.sh state-plan
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh state-apply
./scripts/infrastructure/bootstrap.sh state-backup
./scripts/infrastructure/bootstrap.sh main-init
```

The state bucket is separate from `data_bucket_name`. MWAA Serverless source artifacts use the application-data bucket under `orchestration/mwaa-serverless/`. See [infrastructure-lifecycle.md](infrastructure-lifecycle.md) before migrating old state or deleting an environment.

## 2. Bootstrap protected inputs and packages

Create the Secrets Manager secret `healthcare-realtime/fhir-webhook` in the target region with one JSON key named `FHIR_WEBHOOK_SECRET`. Enter the value through Secrets Manager or another approved secret-management workflow, not in tracked files or terminal output.

The bootstrap wrappers build generated deployment artifacts before Terraform reads their hashes. When running Terraform directly instead of through the wrappers, build them first:

```zsh
for builder in scripts/lambda/build_*.sh; do "$builder"; done
./scripts/glue/build_lineage_package.sh
./airflow/serverless/build_code_package.sh
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
```

## 3. Build ECS images and deploy

Bootstrap the four ECR repositories with a reviewed targeted plan, then build and push Linux AMD64 images with the immutable current-commit tag:

```zsh
./scripts/infrastructure/bootstrap.sh repositories-plan
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh repositories-apply
./scripts/infrastructure/push_images.sh
```

After all four pushes succeed, `push_images.sh` records the generated immutable tag in `.env` and rerenders Terraform inputs. The image script refuses to overwrite an existing ECR tag.

Generate the MWAA definition only after the task definitions, network outputs and Glue job exist. Run each command separately and capture the complete output:

```zsh
set -o pipefail
./scripts/infrastructure/bootstrap.sh foundation-plan 2>&1 | tee /tmp/healthcare-foundation-plan.log
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh foundation-apply 2>&1 | tee /tmp/healthcare-foundation-apply.log
terraform -chdir=infra output -raw glue_job_name
./scripts/infrastructure/bootstrap.sh application-plan 2>&1 | tee /tmp/healthcare-application-plan.log
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh application-apply 2>&1 | tee /tmp/healthcare-application-apply.log
terraform -chdir=infra plan 2>&1 | tee /tmp/healthcare-convergence-plan.log
```

The foundation wrapper builds the Glue lineage package before its targeted plan. The `glue_job_name` command must return a nonempty value before application generation begins. The final plan must report `No changes`. During bootstrap the workflow remains manual-only because no approved model exists yet. The [external prerequisite inventory](external-prerequisites.md) identifies the account and third-party configuration that Terraform does not create.

After any partial apply failure, fix the external prerequisite and run the corresponding plan wrapper again. Review and apply the newly saved plan instead of reusing the plan from the failed operation.

Run direct Terraform commands with `terraform -chdir=infra ...` from the repository root. Both the AWS and AWSCC providers use the generated `aws_region` input. For computed MWAA workflow-version drift, create, review and apply a saved `-refresh-only` plan as shown in the [first-deployment quickstart](quickstart.md); do not run an unsaved root-level `terraform apply`.

After the GitHub OIDC deployment role exists, synchronize the ignored deployment inputs to encrypted AWS storage and configure the protected GitHub environment as described in [deployment.md](deployment.md):

```zsh
./scripts/infrastructure/sync_deployment_config.sh
```

After configuring the protected GitHub environment, run `./scripts/infrastructure/check_prerequisites.sh post-deploy` to verify the deployed external configuration without printing private values.

## 4. Seed FHIR and register delivery

Install and generate the pinned Synthea cohort, then load the selected Patient and Encounter resources into the deployed HAPI endpoint:

```zsh
./scripts/synthea_loader/scripts/install.sh
POPULATION=10 SEED=12345 ./scripts/synthea_loader/scripts/generate.sh
export FHIR_BASE_URL="$(terraform -chdir=infra output -raw hapi_fhir_base_url)"
.venv/bin/python -m scripts.synthea_loader.src.load_fhir
```

Using an approved identity with `secretsmanager:GetSecretValue`, retrieve the webhook secret for the registration process only. Register the HAPI Subscription without writing the value to `.env` or printing it:

```zsh
export FHIR_WEBHOOK_URL="$(terraform -chdir=infra output -raw fhir_webhook_url)"
FHIR_WEBHOOK_SECRET="$(
  aws secretsmanager get-secret-value \
    --secret-id "$FHIR_WEBHOOK_SECRET_ID" \
    --query SecretString \
    --output text \
  | jq -r --arg key "$FHIR_WEBHOOK_SECRET_KEY" '.[$key]'
)" .venv/bin/python -m services.fhir_webhook.app.register_subscription
```

The loader writes the local patient/encounter mapping used by the simulator. The subscription command writes its HAPI response under the ignored service output directory.

## 5. Validate the deployment

First run dbt through the deployed task to materialize the table named by `DBT_ML_TRAINING_TABLE`. Use the [model training guide](model-training.md) to train and publish the first reviewed model, then place its exact version in `.env`, rerun the renderer and apply a reviewed saved plan. That update narrows model-read permissions, updates the task definition and enables the daily schedule configured by `AIRFLOW_PIPELINE_SCHEDULE`.

Use the [demo guide](demo-guide.md) for live Streamlit, Postman REST/WebSocket and CloudWatch checks. After starting an MWAA run, allow 30 minutes before checking its final result; recent complete runs have taken 26 to 28 minutes. Verify Glue, Athena, Great Expectations, dbt, approved-model scoring, prediction refresh, Soda and OpenLineage.
