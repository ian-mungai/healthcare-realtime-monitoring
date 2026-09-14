# First Deployment

## 1. Prepare the clone

From the repository root, install the pinned Python dependencies and create ignored local configuration:

```zsh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_dev.txt
cp .env.example .env
cp infra/development.tfvars.example infra/development.tfvars
cp infra/backend.hcl.example infra/backend.hcl
export AWS_PROFILE="<aws-profile>"
export AWS_REGION="<aws-region>"
export AWS_DEFAULT_REGION="$AWS_REGION"
```

Replace every placeholder in the ignored files and use globally unique bucket names. Leave `ml_approved_model_version` empty for the first deployment; this keeps MWAA in manual-only mode while the training dataset and first model are created. Never commit these files.

## 2. Bootstrap protected inputs and packages

Create the Secrets Manager secret `healthcare-realtime/fhir-webhook` in the target region with one JSON key named `FHIR_WEBHOOK_SECRET`. Enter the value through Secrets Manager or another approved secret-management workflow, not in tracked files or terminal output.

Build generated deployment artifacts before Terraform reads their hashes:

```zsh
for builder in scripts/lambda/build_*.sh; do "$builder"; done
./scripts/glue/build_lineage_package.sh
./airflow/serverless/build_code_package.sh
terraform -chdir=infra init -backend-config=backend.hcl
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
```

## 3. Build ECS images and deploy

Bootstrap ECR repositories with a reviewed targeted plan, then build Linux AMD64 images from `services/vitals_simulator/Dockerfile`, `deploy/dbt/Dockerfile`, `deploy/soda/Dockerfile`, and optionally `deploy/marquez/Dockerfile`. Tag each image immutably, push it, and place the exact tags in `infra/development.tfvars`.

Generate the MWAA definition only after the task definitions and network outputs exist:

```zsh
./airflow/serverless/convert_healthcare_realtime_pipeline.sh
terraform -chdir=infra plan -var-file=development.tfvars -out=tfplan-bootstrap
terraform -chdir=infra show -no-color tfplan-bootstrap
terraform -chdir=infra apply tfplan-bootstrap
terraform -chdir=infra plan -var-file=development.tfvars
```

The final plan must report `No changes`. During bootstrap the workflow remains manual-only because no approved model exists yet.

## 4. Seed FHIR and register delivery

Install and generate the pinned Synthea cohort, then load the selected Patient and Encounter resources into the deployed HAPI endpoint:

```zsh
./scripts/synthea_loader/scripts/install.sh
POPULATION=10 SEED=12345 ./scripts/synthea_loader/scripts/generate.sh
export FHIR_BASE_URL="$(terraform -chdir=infra output -raw hapi_fhir_base_url)"
.venv/bin/python -m scripts.synthea_loader.src.load_fhir
```

Load `FHIR_WEBHOOK_SECRET` into the current shell from the approved private source, then register the HAPI Subscription without printing the value:

```zsh
export FHIR_WEBHOOK_URL="$(terraform -chdir=infra output -raw fhir_webhook_url)"
.venv/bin/python -m services.fhir_webhook.app.register_subscription
```

The loader writes the local patient/encounter mapping used by the simulator. The subscription command writes its HAPI response under the ignored service output directory.

## 5. Validate the deployment

First run dbt through the deployed task to materialize `ml_training_dataset`. Use the [model training guide](model-training.md) to train and publish the first reviewed model, then place its exact version in the ignored `infra/development.tfvars` and apply a reviewed saved plan. That update narrows model-read permissions, updates the task definition, and enables the daily `02:00` UTC MWAA schedule.

Use the [demo guide](demo-guide.md) for live Streamlit, Postman REST/WebSocket, and CloudWatch checks. After starting an MWAA run, allow 15 minutes before checking its final result; verify Glue, Athena, Great Expectations, dbt, approved-model scoring, prediction refresh, Soda, and OpenLineage.
