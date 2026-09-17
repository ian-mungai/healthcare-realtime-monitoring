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

The root requirements file installs the workflow-generator dependencies in the same environment. The verified compatibility set uses Apache Airflow 3.3.1 with SQLAlchemy 2.0.50; do not install Airflow 3.0.x or downgrade SQLAlchemy separately because that recreates the incompatible dependency set.

Replace every placeholder in `.env`. Enter the deployment region once as `AWS_REGION` and use globally unique names for the state and application-data buckets. The state bucket and every regional service are created in `AWS_REGION`. MWAA Serverless definitions and code are stored under `orchestration/mwaa-serverless/` in the application-data bucket. Leave `ML_APPROVED_MODEL_VERSION` empty for the first deployment. Image tags are not first-deployment inputs; the image publishing script generates and records them later.

Set `ENABLE_OPENLINEAGE_COLLECTOR=true` to create the managed collector. Do not add its URL to `.env`; Terraform generates the URL and passes it to project services. When the setting is `false`, lineage uses durable S3 fallback unless the optional external-collector override documented in the [deployment guide](deployment.md) is added.

Find the AWS identity that will sign the dashboard REST and WebSocket requests:

```zsh
aws sts get-caller-identity \
  --profile <aws-profile> \
  --query Arn \
  --output text
```

Set `REALTIME_PATIENT_ACCESS_PRINCIPALS` to that ARN. For an assumed-role or AWS SSO identity, replace only the changing session-name suffix with `*`, for example `arn:aws:sts::<aws-account-id>:assumed-role/<role-name>/*`. Use a comma-separated list for multiple approved identities. Do not use a wildcard for the account, role name or entire principal.

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

The policy command creates or updates customer-managed policies but does not attach them. Before deploying, attach every tracked service policy to the bootstrap identity through the account's approved group or role model. The KMS policy renders its request-tag and resource-tag conditions from `PROJECT_NAME`, so rerun the policy plan and apply after changing that value.

Create the Secrets Manager secret named by `FHIR_WEBHOOK_SECRET_ID` with one JSON key named by `FHIR_WEBHOOK_SECRET_KEY`. Enter the value through Secrets Manager or another approved secret workflow. Do not place the value in `.env`, Terraform input or shell history.

Create the protected GitHub environment only when GitHub deployment is required. A local first deployment does not need GitHub OIDC before the application stack exists.

## 3. Create state and deploy

Create the protected state bucket and initialize a new empty main backend:

```zsh
./scripts/infrastructure/bootstrap.sh state-plan
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh state-apply
./scripts/infrastructure/bootstrap.sh state-backup
./scripts/infrastructure/bootstrap.sh main-init
./scripts/infrastructure/check_prerequisites.sh pre-deploy
```

The state plan must create a new bucket and its protection controls. Stop if Terraform refreshes, imports or updates an existing state bucket; that indicates stale local metadata or a non-first deployment. Do not continue to `main-init` until the state-bucket apply and backup both succeed.

Create the ECR repositories and push immutable images. The publishing script records the generated immutable tag in `.env` and rerenders Terraform inputs only after all four pushes succeed:

```zsh
./scripts/infrastructure/bootstrap.sh repositories-plan
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh repositories-apply
./scripts/infrastructure/push_images.sh
```

Deploy the foundation and full application one command at a time. `pipefail` preserves Terraform failures while `tee` stores complete output in untracked temporary logs:

```zsh
set -o pipefail
./scripts/infrastructure/bootstrap.sh foundation-plan 2>&1 | tee /tmp/healthcare-foundation-plan.log
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh foundation-apply 2>&1 | tee /tmp/healthcare-foundation-apply.log
terraform -chdir=infra output -raw glue_job_name
./scripts/infrastructure/bootstrap.sh application-plan 2>&1 | tee /tmp/healthcare-application-plan.log
CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh application-apply 2>&1 | tee /tmp/healthcare-application-apply.log
terraform -chdir=infra plan 2>&1 | tee /tmp/healthcare-convergence-plan.log
```

The foundation wrapper builds the Glue lineage package and provisions Glue with the other resources required by application generation. The `glue_job_name` command must return a nonempty value before `application-plan` runs. The final plan must report `No changes`. Confirm the SNS email subscription when AWS sends the request. Configure GitHub OIDC later using the [deployment guide](deployment.md) when remote deployment is required.

If application apply fails with an IAM denial, correct and apply the tracked policy first. Do not reuse the failed saved plan because Terraform state may contain resources created before the error. Run `application-plan` again, review its new add/change/destroy summary and apply that new saved plan.

Run direct Terraform commands from the repository root with `-chdir=infra`; running `terraform apply` at the root has no configuration and must not be used. Both AWS providers take their region from the generated Terraform input, so they do not depend on a stale shell region.

When a plan reports only a computed MWAA workflow-version output change, reconcile state with a reviewed refresh-only plan:

```zsh
terraform -chdir=infra plan -refresh-only -input=false -out=tfrefresh
terraform -chdir=infra show -no-color tfrefresh
terraform -chdir=infra apply -input=false tfrefresh
```

Apply `tfrefresh` only when the reviewed plan contains state or output reconciliation and no resource changes.

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
