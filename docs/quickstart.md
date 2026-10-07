---
title: "First Deployment Quickstart"
description: "Prepare a clone and create a synthetic development stack from an empty backend."
last_updated: 2026-10-07
audience: [developer, operator]
---

# First Deployment Quickstart

For developers and operators: prepare a clone and create a synthetic development stack from an empty backend.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Goal](#goal)
- [1. Prepare the Clone](#1-prepare-the-clone)
- [2. Create Account Prerequisites](#2-create-account-prerequisites)
- [3. Create State and Deploy](#3-create-state-and-deploy)
- [4. Seed the Ten-Patient Cohort](#4-seed-the-ten-patient-cohort)
- [5. Run the Fastest Live Demo](#5-run-the-fastest-live-demo)

## Terminology

- **ARN**: Amazon Resource Name.
- **AWS**: Amazon Web Services.
- **CLI**: command-line interface.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **IAM**: Identity and Access Management.
- **IP**: Internet Protocol.
- **JSON**: JavaScript Object Notation.
- **KMS**: Key Management Service.
- **MWAA**: Managed Workflows for Apache Airflow.
- **NAT**: network address translation.
- **OIDC**: OpenID Connect.
- **REST**: Representational State Transfer.
- **SNS**: Simple Notification Service.
- **SSO**: single sign-on.
- **URL**: uniform resource locator.
- **VPC**: virtual private cloud.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<AWS_ACCOUNT_ID>`: aws account id for the selected environment or example.
- `<ROLE_NAME>`: role name for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Goal

Use this path only for the first deployment from a fresh clone when the project has no existing Terraform state bucket, bootstrap state or application resources. It is the shortest reviewed path to a ten-patient live demo in a standard commercial AWS account. Allow 60 to 90 minutes for infrastructure and image builds, then 10 minutes for the realtime demo. The optional full analytical validation adds about 30 minutes.

These steps create the development environment from the selected `${PROJECT_ENV_FILE:-.env}` file. To create production, export `PROJECT_ENV_FILE=.env.production` first and follow the [environments guide](environments.md).

Do not use this quickstart to recreate a destroyed environment with a retained state bucket or to migrate an existing deployment. Follow the [infrastructure lifecycle guide](infrastructure-lifecycle.md) for those workflows.

The target region must provide at least two Availability Zones and support the services checked by the regional readiness command, including Managed Workflows for Apache Airflow (MWAA) Serverless. A first deployment creates a new persistent state bucket in the target region and initializes an empty Terraform backend.

## 1. Prepare the Clone

From the repository root:

1. Run the following command block:

    ```zsh
    python3.12 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements_dev.txt
    if [ ! -e "${PROJECT_ENV_FILE:-.env}" ]; then
      cp .env.example "${PROJECT_ENV_FILE:-.env}"
    fi
    ```

    The root requirements file installs the workflow-generator dependencies in the same environment. The verified compatibility set uses Apache Airflow 3.3.1 with SQLAlchemy 2.0.50; do not install Airflow 3.0.x or downgrade SQLAlchemy separately because that recreates the incompatible dependency set.

    Replace every placeholder in the selected `${PROJECT_ENV_FILE:-.env}` file. No personal Internet Protocol (IP) address is needed: the HAPI load balancer accepts only the network address translation (NAT) gateway and the cohort load and subscription registration run as an Elastic Container Service (ECS) task inside the virtual private cloud (VPC) ([Fast Healthcare Interoperability Resources (FHIR) setup tasks](fhir-setup-tasks.md)). Patient IDs are not user inputs: the generated FHIR resource map supplies them before the full application plan. Enter the deployment region once as `AWS_REGION` and use globally unique names for the state and application-data buckets. The state bucket and every regional service are created in `AWS_REGION`. MWAA Serverless definitions and code are stored under `orchestration/mwaa-serverless/` in the application-data bucket. Leave `ML_APPROVED_MODEL_VERSION` empty for the first deployment. Image tags are not first-deployment inputs; the image publishing script generates and records them later.

    Set `ENABLE_OPENLINEAGE_COLLECTOR=true` in the selected environment file to create the managed collector. Do not add its URL to that file; Terraform generates the URL and passes it to project services. When the setting is `false`, lineage uses durable S3 fallback unless the optional external-collector override documented in the [deployment guide](deployment.md) is added.

    Load the completed local settings before using any AWS command:

2. Run the following command block:

    ```zsh
    set -a
    source "${PROJECT_ENV_FILE:-.env}"
    set +a
    ```

    Find the AWS identity that will sign the dashboard Representational State Transfer (REST) and WebSocket requests. The profile comes from the selected environment file; do not enter it a second time:

3. Run the following command block:

    ```zsh
    aws sts get-caller-identity \
      --profile "$AWS_PROFILE" \
      --query Arn \
      --output text
    ```

    Set `REALTIME_PATIENT_ACCESS_PRINCIPALS` to that Amazon Resource Name (ARN). For an assumed-role or AWS single sign-on (SSO) identity, replace only the changing session-name suffix with `*`, for example `arn:aws:sts::<AWS_ACCOUNT_ID>:assumed-role/<ROLE_NAME>/*`. Use a comma-separated list for multiple approved identities. Do not use a wildcard for the account, role name or entire principal.

    Render the two ignored Terraform input files. Do not edit the generated files directly:

4. Run the following command block:

    ```zsh
    ./scripts/infrastructure/render_project_config.sh
    ```

    The documented local workflow requires a named AWS command-line interface (CLI) profile in `AWS_PROFILE`. An SSO-backed profile is supported after `aws sso login --profile "$AWS_PROFILE"`. Environment-only credentials without a named profile are outside this quickstart.

    Confirm the local toolchain and selected AWS identity:

5. Run the following command block:

    ```zsh
    ./scripts/infrastructure/check_prerequisites.sh local
    .venv/bin/python scripts/infrastructure/check_region_readiness.py \
      --profile "$AWS_PROFILE" \
      --region "$AWS_REGION"
    ```

## 2. Create Account Prerequisites

Use a temporary administrator or approved bootstrap identity for these account-level operations. Plan every tracked customer-managed policy before applying it:

1. Run the following command block:

    ```zsh
    .venv/bin/python infra/iam/scripts/manage_policies.py plan \
      --profile "$AWS_PROFILE" \
      --region "$AWS_REGION"

    ```

    Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

2. Apply only the reviewed and approved action:

    ```zsh
    CONFIRM_IAM_POLICIES=apply-healthcare-realtime-policies \
      .venv/bin/python infra/iam/scripts/manage_policies.py apply \
      --profile "$AWS_PROFILE" \
      --region "$AWS_REGION"
    ```

    The policy command creates or updates customer-managed policies but does not attach them. Before deploying, attach every tracked service policy to the bootstrap identity through the account's approved group or role model. The Key Management Service (KMS) policy renders its request-tag and resource-tag conditions from `PROJECT_NAME`, so rerun the policy plan and apply after changing that value.

    Create the Secrets Manager secret named by `FHIR_WEBHOOK_SECRET_ID` with one JavaScript Object Notation (JSON) key named by `FHIR_WEBHOOK_SECRET_KEY`. Enter the value through Secrets Manager or another approved secret workflow. Do not place the value in the selected `${PROJECT_ENV_FILE:-.env}` file, Terraform input or shell history.

    Your own identity never reads this secret: the registration in step 4 runs as the FHIR setup task, whose role reads it inside AWS. The prerequisite check only confirms that a secret with this name exists. Apply the policy templates after setting `FHIR_WEBHOOK_SECRET_ID`, because the Secrets Manager policy is scoped to that name.

    Create the protected GitHub environment only when GitHub deployment is required. A local first deployment does not need GitHub OpenID Connect (OIDC) before the application stack exists.

## 3. Create State and Deploy

Create the protected state bucket and initialize a new empty main backend:

1. Run the following command block:

    ```zsh
    ./scripts/infrastructure/bootstrap.sh state-plan
    ```

    Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

2. Apply only the reviewed and approved action:

    ```zsh
    CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh state-apply
    ```

3. Back up the applied bootstrap state:

    ```zsh
    ./scripts/infrastructure/bootstrap.sh state-backup
    ```

    Confirm the protected backup exists before initialization.

4. Initialize the application backend:

    ```zsh
    ./scripts/infrastructure/bootstrap.sh main-init
    ```

5. Check deployment prerequisites:

    ```zsh
    ./scripts/infrastructure/check_prerequisites.sh pre-deploy
    ```

    The state plan must create a new bucket and its protection controls. Stop if Terraform refreshes, imports or updates an existing state bucket; that indicates stale local metadata or a non-first deployment. Do not continue to `main-init` until the state-bucket apply and backup both succeed.

    Create the Elastic Container Registry (ECR) repositories and push immutable images. The publishing script records the generated immutable tag in the selected environment file and rerenders Terraform inputs only after all four pushes succeed:

6. Run the following command block:

    ```zsh
    ./scripts/infrastructure/bootstrap.sh repositories-plan
    ```

    Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

    The simulator image packages `services/vitals_simulator/data/blood_pressure_readings.json`, which must cover every cohort patient. Before pushing images, generate the cohort with the two Synthea commands from step 4 and export the readings with `PYTHONPATH=. .venv/bin/python scripts/export_vitals_simulator_bp.py`. If the file changes, commit it first, because the image tag names the commit. Otherwise the simulator stops with "No blood pressure readings found for Synthea patient".

7. Apply only the reviewed and approved action:

    ```zsh
    CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh repositories-apply
    ./scripts/infrastructure/push_images.sh
    ```

    Deploy the foundation one command at a time. `pipefail` preserves Terraform failures while `tee` stores complete output in untracked temporary logs:

8. Run the following command block:

    ```zsh
    set -o pipefail
    ./scripts/infrastructure/bootstrap.sh foundation-plan 2>&1 | tee /tmp/healthcare-foundation-plan.log
    ```

    Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

9. Apply only the reviewed and approved action:

    ```zsh
    CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh foundation-apply 2>&1 | tee /tmp/healthcare-foundation-apply.log
    terraform -chdir=infra output -raw glue_job_name
    ```

    The foundation wrapper builds the Glue lineage package and provisions HAPI FHIR, the data bucket and Glue with the other resources required by cohort loading and application generation. The `glue_job_name` command must return a nonempty value before continuing.

    If application apply fails with an Identity and Access Management (IAM) denial, correct and apply the tracked policy first. Do not reuse the failed saved plan because Terraform state may contain resources created before the error. Run `application-plan` again, review its new add/change/destroy summary and apply that new saved plan.

    Run direct Terraform commands from the repository root with `-chdir=infra`; running `terraform apply` at the root has no configuration and must not be used. Both AWS providers take their region from the generated Terraform input, so they do not depend on a stale shell region.

    When a plan reports only a computed MWAA workflow-version output change, reconcile state with a reviewed refresh-only plan:

10. Run the following command block:

    ```zsh
    terraform -chdir=infra plan -refresh-only -input=false -var-file=deployment.auto.tfvars.json -out=tfrefresh
    terraform -chdir=infra show -no-color tfrefresh
    ```

    Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

11. Apply only the reviewed and approved action:

    ```zsh
    terraform -chdir=infra apply -input=false tfrefresh
    ```

    Apply `tfrefresh` only when the reviewed plan contains state or output reconciliation and no resource changes.

## 4. Seed the Ten-Patient Cohort

Generate the pinned synthetic cohort locally, load it into HAPI FHIR with the FHIR setup task and synchronize the HAPI-assigned IDs before planning the full application:

Synthea generates 100 adult patients, aged 18 to 90, with the pinned seed; with `COHORT_SIZE` unset, the setup task loads the first ten. The other 90 serve local development (Local Stack).

1. Run the following command block:

    ```zsh
    ./scripts/synthea_loader/scripts/install.sh
    POPULATION=100 SEED=4817263 ./scripts/synthea_loader/scripts/generate.sh
    ./scripts/infrastructure/run_fhir_setup.sh load

    ./scripts/infrastructure/bootstrap.sh application-plan 2>&1 | tee /tmp/healthcare-application-plan.log
    ```

    Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

2. Apply only the reviewed and approved action:

    ```zsh
    CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap ./scripts/infrastructure/bootstrap.sh application-apply 2>&1 | tee /tmp/healthcare-application-apply.log
    terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json 2>&1 | tee /tmp/healthcare-convergence-plan.log

    ./scripts/infrastructure/run_fhir_setup.sh register
    ```

    `run_fhir_setup.sh load` uploads the generated bundles, runs the loader inside the VPC, downloads the published map and rerenders the ignored Terraform inputs with the ten HAPI patient IDs. `run_fhir_setup.sh register` registers the webhook subscription from inside AWS, reading the secret there and reuses an existing subscription. Each run writes a report under `artifacts/e2e/fhir_setup/`; see [FHIR setup tasks](fhir-setup-tasks.md). The live dashboard reads the same generated map directly. Review the application plan before applying it. The final convergence plan must report `No changes`. Confirm the Simple Notification Service (SNS) email subscription when AWS sends the request. Configure GitHub OIDC later using the [deployment guide](deployment.md) when remote deployment is required.

## 5. Run the Fastest Live Demo

Start one simulator task:

1. Run the following command block:

    ```zsh
    ./scripts/demo/start_vitals_demo.sh
    ./scripts/demo/status_vitals_demo.sh
    ```

    In a second terminal, start the live cohort dashboard:

2. Run the following command block:

    ```zsh
    ./scripts/demo/start_live_dashboard.sh
    ```

    Confirm all ten patients are present. Heart rate, respiratory rate and oxygen saturation must be no more than ten seconds old. Blood pressure follows its separate five-minute publication cadence and remains current for up to 310 seconds. Run the REST, WebSocket and CloudWatch checks in the [demo guide](demo-guide.md), then stop the simulator:

3. Run the following command block:

    ```zsh
    ./scripts/demo/stop_vitals_demo.sh
    ./scripts/demo/status_vitals_demo.sh
    ```

    The realtime demo does not require an approved model. To show existing approved-model results, launch the separate analytics dashboard in a third terminal:

4. Run the following command block:

    ```zsh
    ./scripts/demo/start_model_analytics_dashboard.sh
    ```

    Confirm the analytics dashboard shows the approved model version and its synthetic, nonclinical scope. Realtime monitoring remains available without an approved model.

### Complete the Analytical Path

Prerequisites:

- A deployed cohort, no competing simulator task and an approved analytical demo session.
- A private environment file and approval for any exact model or optimizer deployment plan.

1. Run the simulator for at least 30 minutes so its fresh encounters complete both analytical windows. Follow [Analytics and Recovery Evidence](demo-guide.md#analytics-and-recovery-evidence) for the start, stop and workflow procedure.
2. Stop the simulator and build the analytical tables with dbt using the same demo procedure.
3. Follow [Model Training](model-training.md#train-locally-from-athena) and [Activate a Reviewed Model](model-training.md#activate-a-reviewed-model). Keep MWAA manual-only until the published immutable model is reviewed and the exact activation plan is approved.
4. Run MWAA and verify the workflow succeeds, the serving predictions use the approved model and dbt and Soda checks pass. Allow another 30 minutes for the workflow.
5. Confirm the processed Iceberg table exists after that successful workflow. Set `ENABLE_ICEBERG_TABLE_OPTIMIZERS=true` in the selected `${PROJECT_ENV_FILE:-.env}` file, then render and inspect a saved optimizer plan:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-optimizers
   terraform -chdir=infra show -no-color tfplan-optimizers
   ```

6. Obtain approval for its exact changes and apply that plan:

   ```zsh
   terraform -chdir=infra apply tfplan-optimizers
   ```

7. Verify the selected processed table has managed compaction, snapshot retention and orphan-file deletion enabled.

Each simulator task creates a fresh encounter for every patient. Runs planned to cover the full 30-minute window favor each patient's less frequent scenario among tagged encounters in HAPI FHIR. Ties use `SIMULATOR_SCENARIO_SEED` and the patient identifier or a random choice; shorter planned runs use the seed or random choice without counting or tagging history. The [star-schema reference](analytics-star-schema.md#feature-and-label-construction) defines planned duration and the startup-tag boundary.

Start with two complete runs and inspect analytical readiness. Interrupted runs and retained tagged history mean two runs do not guarantee actual class coverage. Keep `ML_APPROVED_MODEL_VERSION` empty and MWAA in manual-only mode until eligible observations produce both classes in both patient-grouped partitions without patient leakage and a reviewed immutable model artifact has been published. Do not bypass the class-readiness gate to complete a first deployment.
