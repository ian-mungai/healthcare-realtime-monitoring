# First Deployment

## 1. Prepare the clone

From the repository root, install the pinned Python dependencies and create ignored local configuration:

```zsh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_dev.txt
cp .env.example .env
cp infra/development.tfvars.example infra/development.tfvars
cp infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars
```

Replace every placeholder in the ignored files and use globally unique bucket names. `.env` contains only local or externally managed prerequisites; Terraform-created endpoints and resource identifiers come from Terraform outputs. Values already exported in the shell take precedence. Leave `ml_approved_model_version` empty for the first deployment; this keeps MWAA in manual-only mode while the training dataset and first model are created. Never commit these files.

Create the persistent state bucket before initializing the application stack:

```zsh
./scripts/infrastructure/bootstrap.sh state-plan
terraform -chdir=infra/bootstrap show -no-color tfplan-state-bootstrap
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh state-apply
./scripts/infrastructure/bootstrap.sh state-backup
./scripts/infrastructure/bootstrap.sh main-init
```

The state bucket is separate from `data_bucket_name` and `mwaa_source_bucket_name`. See [infrastructure-lifecycle.md](infrastructure-lifecycle.md) before migrating old state or deleting an environment.

## 2. Bootstrap protected inputs and packages

Create the Secrets Manager secret `healthcare-realtime/fhir-webhook` in the target region with one JSON key named `FHIR_WEBHOOK_SECRET`. Enter the value through Secrets Manager or another approved secret-management workflow, not in tracked files or terminal output.

Build generated deployment artifacts before Terraform reads their hashes:

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
terraform -chdir=infra show -no-color tfplan-bootstrap-ecr
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh repositories-apply
./scripts/infrastructure/push_images.sh
```

Place the four tags printed by `push_images.sh` into the ignored `infra/development.tfvars`. The script refuses to overwrite an existing tag.

Generate the MWAA definition only after the task definitions and network outputs exist:

```zsh
./scripts/infrastructure/bootstrap.sh foundation-plan
terraform -chdir=infra show -no-color tfplan-bootstrap-foundation
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh foundation-apply
./scripts/infrastructure/bootstrap.sh application-plan
terraform -chdir=infra show -no-color tfplan-bootstrap-application
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh application-apply
terraform -chdir=infra plan -var-file=development.tfvars
```

The final plan must report `No changes`. Run `./scripts/infrastructure/check_prerequisites.sh` to verify the external configuration without printing private values. During bootstrap the workflow remains manual-only because no approved model exists yet. The [external prerequisite inventory](external-prerequisites.md) identifies the account and third-party configuration that Terraform does not create.

After the GitHub OIDC deployment role exists, synchronize the ignored deployment inputs to encrypted AWS storage and configure the protected GitHub environment as described in [deployment.md](deployment.md):

```zsh
./scripts/infrastructure/sync_deployment_config.sh
```

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

First run dbt through the deployed task to materialize the table named by `DBT_ML_TRAINING_TABLE`. Use the [model training guide](model-training.md) to train and publish the first reviewed model, then place its exact version in the ignored `infra/development.tfvars` and apply a reviewed saved plan. That update narrows model-read permissions, updates the task definition and enables the daily schedule configured by `AIRFLOW_PIPELINE_SCHEDULE`.

Use the [demo guide](demo-guide.md) for live Streamlit, Postman REST/WebSocket and CloudWatch checks. After starting an MWAA run, allow 30 minutes before checking its final result; recent complete runs have taken 26 to 28 minutes. Verify Glue, Athena, Great Expectations, dbt, approved-model scoring, prediction refresh, Soda and OpenLineage.
