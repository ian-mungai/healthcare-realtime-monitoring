# First Deployment Quickstart

## Goal

Use this path only for the first deployment from a fresh clone when the project has no existing Terraform state bucket, bootstrap state or application resources. It is the shortest reviewed path to a ten-patient live demo in a standard commercial AWS account. Allow 60 to 90 minutes for infrastructure and image builds, then 10 minutes for the realtime demo. The optional full analytical validation adds about 30 minutes.

Do not use this quickstart to recreate a destroyed environment with a retained state bucket or to migrate an existing deployment. Follow the [infrastructure lifecycle guide](infrastructure-lifecycle.md) for those workflows.

The target region must provide at least two Availability Zones and support the services checked by the regional readiness command, including MWAA Serverless. A first deployment creates a new persistent state bucket in the target region and initializes an empty Terraform backend.

## 1. Prepare the clone

From the repository root:

```zsh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_dev.txt
cp .env.example .env
```

Replace every placeholder in `.env`. Use globally unique names for the state, application-data and MWAA source buckets. Leave `ML_APPROVED_MODEL_VERSION` empty for the first deployment. Patient IDs, bucket names, regions and image tags are entered only in this file.

Render the two ignored Terraform input files. Do not edit the generated files directly:

```zsh
./scripts/infrastructure/render_project_config.sh
```

The documented local workflow requires a named AWS CLI profile in `AWS_PROFILE`. An SSO-backed profile is supported after `aws sso login --profile "$AWS_PROFILE"`. Environment-only credentials without a named profile are outside this quickstart.

Load the non-secret local settings into the current shell:

```zsh
set -a
source .env
set +a
```

Confirm the local toolchain and selected AWS identity:

```zsh
./scripts/infrastructure/check_prerequisites.sh local
.venv/bin/python scripts/infrastructure/check_region_readiness.py \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
```

## 2. Create account prerequisites

Use a temporary administrator or approved bootstrap identity for these account-level operations. Plan every tracked customer-managed policy before applying it:

```zsh
.venv/bin/python infra/iam/scripts/manage_policies.py plan \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"

CONFIRM_IAM_POLICIES=apply-healthcare-realtime-policies \
  .venv/bin/python infra/iam/scripts/manage_policies.py apply \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
```

Create the Secrets Manager secret named by `FHIR_WEBHOOK_SECRET_ID` with one JSON key named by `FHIR_WEBHOOK_SECRET_KEY`. Enter the value through Secrets Manager or another approved secret workflow. Do not place the value in `.env`, Terraform input or shell history.

Create the protected GitHub environment only when GitHub deployment is required. A local first deployment does not need GitHub OIDC before the application stack exists.

## 3. Create state and deploy

Create the protected state bucket and initialize a new empty main backend:

```zsh
./scripts/infrastructure/bootstrap.sh state-plan
terraform -chdir=infra/bootstrap show -no-color tfplan-state-bootstrap
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh state-apply
./scripts/infrastructure/bootstrap.sh state-backup
./scripts/infrastructure/bootstrap.sh main-init
./scripts/infrastructure/check_prerequisites.sh pre-deploy
```

The state plan must create a new bucket. Stop if Terraform refreshes, imports or updates an existing state bucket; that indicates this is not a first deployment and the infrastructure lifecycle workflow applies instead.

Create the ECR repositories and push immutable images. Place the four printed image tags in `.env`, then rerun the renderer:

```zsh
./scripts/infrastructure/bootstrap.sh repositories-plan
terraform -chdir=infra show -no-color tfplan-bootstrap-ecr
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh repositories-apply
./scripts/infrastructure/push_images.sh
./scripts/infrastructure/render_project_config.sh
```

Deploy the foundation and full application:

```zsh
./scripts/infrastructure/bootstrap.sh foundation-plan
terraform -chdir=infra show -no-color tfplan-bootstrap-foundation
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh foundation-apply
./scripts/infrastructure/bootstrap.sh application-plan
terraform -chdir=infra show -no-color tfplan-bootstrap-application
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
  ./scripts/infrastructure/bootstrap.sh application-apply
terraform -chdir=infra plan
```

The final plan must report `No changes`. Confirm the SNS email subscription when AWS sends the request. Configure GitHub OIDC later using the [deployment guide](deployment.md) when remote deployment is required.

## 4. Seed the ten-patient cohort

Generate the pinned synthetic cohort, load it into HAPI FHIR and register the webhook subscription:

```zsh
./scripts/synthea_loader/scripts/install.sh
POPULATION=10 SEED=12345 ./scripts/synthea_loader/scripts/generate.sh
export FHIR_BASE_URL="$(terraform -chdir=infra output -raw hapi_fhir_base_url)"
.venv/bin/python -m scripts.synthea_loader.src.load_fhir

export FHIR_WEBHOOK_URL="$(terraform -chdir=infra output -raw fhir_webhook_url)"
FHIR_WEBHOOK_SECRET="$(
  aws secretsmanager get-secret-value \
    --secret-id "$FHIR_WEBHOOK_SECRET_ID" \
    --query SecretString \
    --output text |
  jq -r --arg key "$FHIR_WEBHOOK_SECRET_KEY" '.[$key]'
)" .venv/bin/python -m services.fhir_webhook.app.register_subscription
```

## 5. Run the fastest live demo

Start one simulator task:

```zsh
./scripts/demo/start_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

In a second terminal, start the live cohort dashboard:

```zsh
./scripts/demo/start_live_dashboard.sh
```

Confirm all ten patients are present. Heart rate, respiratory rate and oxygen saturation must be no more than ten seconds old. Blood pressure follows its separate five-minute publication cadence and remains current for up to 310 seconds. Run the REST, WebSocket and CloudWatch checks in the [demo guide](demo-guide.md), then stop the simulator:

```zsh
./scripts/demo/stop_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

The realtime demo does not require an approved model. To show existing approved-model results, launch the separate analytics dashboard in a third terminal:

```zsh
./scripts/demo/start_model_analytics_dashboard.sh
```

For the complete analytical and data-science path, run dbt, follow the [model training guide](model-training.md), apply the approved model version and run MWAA. Allow 30 minutes for that workflow.
