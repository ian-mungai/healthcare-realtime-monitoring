---
title: "Operations Runbook"
description: "Verify service health, diagnose failures and recover bounded processing paths."
last_updated: 2026-10-02
audience: [developer, operator]
---

# Operations Runbook

For developers and operators: verify service health, diagnose failures and recover bounded processing paths.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Scope](#scope)
- [Prerequisites](#prerequisites)
- [CI and Deployment Gate](#ci-and-deployment-gate)
- [Demo Startup](#demo-startup)
- [Live Validation](#live-validation)
- [Incident Triage and Recovery](#incident-triage-and-recovery)
- [Demo Shutdown and Cost Control](#demo-shutdown-and-cost-control)
- [Evidence Handoff](#evidence-handoff)

## Terminology

- **ARN**: Amazon Resource Name.
- **AWS**: Amazon Web Services.
- **CI**: continuous integration.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **IAM**: Identity and Access Management.
- **ID**: identifier.
- **JSONL**: JSON Lines.
- **MWAA**: Managed Workflows for Apache Airflow.
- **NAT**: network address translation.
- **OIDC**: OpenID Connect.
- **REST**: Representational State Transfer.
- **SSO**: single sign-on.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<AWS_ACCOUNT_ID>`: aws account id for the selected environment or example.
- `<DASHBOARD_USER>`: dashboard user for the selected environment or example.
- `<LISTED_POLICY_NAME>`: listed policy name for the selected environment or example.
- `<REJECTION_REASON>`: rejection reason for the selected environment or example.
- `<ROLE_NAME>`: role name for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Scope

This runbook covers the portfolio demonstration environment. It uses synthetic data only. Do not use it as a clinical production procedure.

## Prerequisites

From any directory within a repository clone, load the ignored environment that identifies the target environment:

1. Run the following command block:

   ```zsh
   cd "$(git rev-parse --show-toplevel)"
   set -a
   source "${PROJECT_ENV_FILE:-.env}"
   set +a
   ```

   Never place credentials, signed headers, account identifiers, endpoint identifiers or secret values in shell history, screenshots or public evidence.

### Patient Access Policy

Before the foundation deployment, enter authorized Identity and Access Management (IAM) principal patterns in `REALTIME_PATIENT_ACCESS_PRINCIPALS` inside the selected `${PROJECT_ENV_FILE:-.env}` file. `./scripts/infrastructure/run_fhir_setup.sh load` loads the generated cohort into HAPI, publishes the map and rerenders Terraform inputs with the ten HAPI-assigned IDs before the full application plan. For a local HAPI, `python -m scripts.synthea_loader.src.publish_resource_map` publishes a locally built map the same way:

1. Configure the following settings:

   ```dotenv
   REALTIME_PATIENT_ACCESS_PRINCIPALS=arn:aws:iam::<AWS_ACCOUNT_ID>:user/<DASHBOARD_USER>
   ```

   Obtain the principal Amazon Resource Name (ARN) used by the dashboard with `aws sts get-caller-identity --profile "$AWS_PROFILE" --query Arn --output text`. The renderer gives each comma-separated principal access to the same canonical patient cohort. Use an exact IAM user ARN. For an assumed-role or AWS single sign-on (SSO) identity, replace only the changing session-name suffix with `*`, for example `arn:aws:sts::<AWS_ACCOUNT_ID>:assumed-role/<ROLE_NAME>/*`. Do not use a wildcard for the account, role name or entire principal.

   All supported Fast Healthcare Interoperability Resources (FHIR) webhook routes require `X-Webhook-Secret`, including health, metadata, the Observation profile and subscription handshake requests. The metadata response advertises the project-specific vital-sign Observation profile. That profile makes `Observation.encounter` mandatory because the encounter defines the analytics window; otherwise-valid generic FHIR R4 Observations without an Encounter are rejected. Retrieve the machine-readable profile from `GET /webhooks/fhir/StructureDefinition/healthcare-realtime-vital-observation`. The Lambda refreshes its cached Secrets Manager value within five minutes, so secret rotation does not require a cold start.

   Create the one local input file, complete it and render both Terraform configurations:

2. Run the following command block:

   ```zsh
   if [ ! -e "${PROJECT_ENV_FILE:-.env}" ]; then
     cp .env.example "${PROJECT_ENV_FILE:-.env}"
   fi
   ./scripts/infrastructure/render_project_config.sh
   ```

### Terraform State

Use the dedicated, private, versioned state bucket created by `infra/bootstrap`. It must be separate from the application-data bucket so application teardown cannot remove its own state. Managed Workflows for Apache Airflow (MWAA) Serverless source artifacts live under `orchestration/mwaa-serverless/` in the application-data bucket:

1. Run the following command block:

   ```zsh
   ./scripts/infrastructure/bootstrap.sh state-plan
   ```

   For a new environment, review and apply the state plan, then initialize the main stack:

2. Run the following command block:

   ```zsh
   CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
     ./scripts/infrastructure/bootstrap.sh state-apply
   ./scripts/infrastructure/bootstrap.sh state-backup
   ./scripts/infrastructure/bootstrap.sh main-init
   ```

   `state-backup` copies the ignored local bootstrap state into the protected state bucket; do not run `main-init` until it succeeds. See the [infrastructure lifecycle guide](infrastructure-lifecycle.md#persistent-state-bootstrap) for restoring it.

   For an existing deployment, make a private backup and migrate it once:

3. Run the following command block:

   ```zsh
   CONFIRM_BOOTSTRAP=apply-healthcare-realtime-bootstrap \
     ./scripts/infrastructure/bootstrap.sh main-migrate
   ```

   Confirm that the state object exists in the configured bucket before removing any local state backup. S3 versioning provides recovery and Terraform's `use_lockfile` setting provides native locking.

## CI and Deployment Gate

The CI workflow runs Python tests, linting, type checks, Soda syntax checks, Terraform format and validation, generated-workflow validation, deployment-package checks and container builds on pull requests and updates to `main`. A separate Repository Checks job runs the pre-commit hooks described in the [quality checks guide](quality-checks.md), scans the full Git history with gitleaks and proves each check against good and bad samples. Infrastructure deployment uses the manual OpenID Connect (OIDC)-authenticated workflow and protected environment described in the [deployment guide](deployment.md).

Before infrastructure deployment, run:

1. Run the following command block:

   ```zsh
   terraform -chdir=infra fmt -check -recursive
   terraform -chdir=infra validate
   ./scripts/infrastructure/render_project_config.sh --check
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-operations
   terraform -chdir=infra show -no-color tfplan-operations
   ```

   Review every planned action, then apply only the saved plan with `terraform -chdir=infra apply tfplan-operations`. After deployment, repeat `terraform plan` and expect `No changes`.

## Demo Startup

Check current simulator state first:

1. Run the following command block:

   ```zsh
   ./scripts/demo/status_vitals_demo.sh
   ```

   Start a single simulator task only when the status command reports it is stopped:

2. Run the following command block:

   ```zsh
   ./scripts/demo/start_vitals_demo.sh
   ```

   The start script discovers the project network and task security group at runtime. It refuses to start a second simulator task for the same family.

## Live Validation

While the simulator is running, confirm all of the following:

- The cohort dashboard shows current values for all simulated patients.
- Heart rate, respiratory rate and oxygen saturation use a ten-second freshness ceiling. Blood pressure uses a 310-second ceiling for its five-minute cadence; historical trends remain available.
- The live processing-latency and WebSocket-delivery alarms are `OK`.
- The Representational State Transfer (REST) vitals endpoint returns a current record using AWS IAM authorization.
- A Postman WebSocket connection authenticated with AWS IAM receives current patient updates.
- The current-state table advances event timestamps for the simulated cohort.

HAPI queues subscription notifications immediately and polls pending subscription work every second. If current values repeatedly cross the 10-second display ceiling, inspect HAPI logs and database load before changing the five-second simulator cadence.

Use temporary Postman variables for endpoints and authorization. Do not export collections containing signed headers or private environment values.

### End-to-End Scenarios

With no simulator task running, `.venv/bin/python -m e2e.run session` runs the realtime, access, rejection and replay scenarios and writes a report for each under `artifacts/e2e/`. Scenario details, prerequisites and the deployment-session steps are in the [end-to-end test plan](e2e-test-plan.md).

The replay scenario adds a temporary inline Deny policy named `healthcare_realtime_e2e_replay_<RUN_ID>` to the realtime processor role and always removes it when the run ends. If a run is killed before its cleanup, the Deny stays and keeps blocking writes for that run's synthetic patient only. List and remove any leftover:

1. Run the following command block:

   ```zsh
   PROCESSOR_ROLE="$(aws lambda get-function-configuration \
     --function-name "$(terraform -chdir=infra output -raw realtime_processor_lambda_name)" \
     --query Role --output text)"
   PROCESSOR_ROLE="${PROCESSOR_ROLE##*/}"
   aws iam list-role-policies --role-name "$PROCESSOR_ROLE" \
     --query "PolicyNames[?starts_with(@, 'healthcare_realtime_e2e_replay_')]" --output text
   aws iam delete-role-policy --role-name "$PROCESSOR_ROLE" --policy-name "<LISTED_POLICY_NAME>"
   ```

## Incident Triage and Recovery

1. Check the two CloudWatch dashboards for processor errors, Kinesis iterator age, processing latency and WebSocket delivery failures.
2. Check the simulator task status and its CloudWatch log stream.
3. Check the webhook Lambda log stream for authorization or secret-retrieval failures.
4. For processing failures, inspect the encrypted failure queue and replay dead-letter queue before redriving any message.
5. Correct the underlying data or deployment cause, then use the replay workflow only with a reviewed sequence range and a bounded replay attempt.
6. Verify fresh current-state records, dashboard updates and alarm recovery before closing the incident.

### Analytical Quarantine Recovery

Inspect rejected rows through Athena before replaying anything:

1. Use the following query in the documented database context:

   ```sql
   SELECT rejection_reason, count(*) AS rejected_rows
   FROM ${ATHENA_SOURCE_DATABASE}.${ATHENA_QUARANTINE_TABLE}
   GROUP BY rejection_reason
   ORDER BY rejected_rows DESC;
   ```

   Export a bounded reason group to local JSON Lines (JSONL), correct the rejected fields and validate the file without publishing:

2. Run the following command block:

   ```zsh
   export DATA_BUCKET="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"
   export VITALS_STREAM="$(terraform -chdir=infra output -raw kinesis_stream_name)"
   export QUARANTINE_REVIEW_FILE="${TMPDIR:-/tmp}/healthcare-realtime-quarantine-review.jsonl"

   .venv/bin/python scripts/quarantine/manage_quarantine.py --region "$AWS_REGION" export \
     --bucket "$DATA_BUCKET" \
     --rejection-reason "<REJECTION_REASON>" \
     --output "$QUARANTINE_REVIEW_FILE"

   .venv/bin/python scripts/quarantine/manage_quarantine.py --region "$AWS_REGION" replay \
     --input "$QUARANTINE_REVIEW_FILE" \
     --stream-name "$VITALS_STREAM"
   ```

   Review the validated count, then publish the corrected rows by repeating the replay command with `--confirm-replay`. Replayed rows retain the original observation identifier (ID), use `source=quarantine_replay`, pass through Firehose and Glue again and remain idempotent at the analytical `(observation_id, loinc_code)` grain.

### Optional Lineage Collector

The analytical workflow always emits OpenLineage events. When the shared collector is disabled, Glue, Athena, dbt, Great Expectations and Soda store events in the project data bucket. Terraform omits the optional `--OPENLINEAGE_URL` Glue argument when no collector URL is configured. Do not add the argument with an empty value because AWS Glue treats an empty option as a missing command-line value.

After correcting a Glue deployment failure, apply the reviewed Terraform change and start a fresh MWAA workflow run. The Glue sensor may retry while the failed job reaches its terminal state; verify the new Glue run ID before interpreting a sensor retry as another processing attempt.

Terraform creates both the dbt presentation database and the published-model database before analytical Elastic Container Service (ECS) tasks run. The dbt task role manages tables and partitions inside its assigned database but cannot create new Glue databases. If a first dbt run reports `glue:CreateDatabase`, confirm the Terraform-managed dbt database exists before changing IAM permissions.

### Simulator Publication Failures

The simulator isolates FHIR publication failures by patient. The HAPI client owns the single bounded retry policy and reuses deterministic observation identifiers, so partial retries do not create duplicate observations. Patients with permanent failures are disabled for the remainder of the task while healthy patient streams continue.

Each cycle emits a structured summary with `status`, patient counts, disabled patients, the retryable failure ratio and consecutive systemic failure cycles. The task exits only when retryable failures meet the configured cohort ratio for three consecutive cycles. Cycle overruns and patient publication failures publish CloudWatch metrics from structured log entries and notify through the project alert topic.

The deployed defaults are controlled by:

- `SIMULATOR_FHIR_MAX_ATTEMPTS=2`
- `SIMULATOR_FHIR_RETRY_BACKOFF_SECONDS=2`
- `SIMULATOR_MAX_CONSECUTIVE_FAILED_CYCLES=3`
- `SIMULATOR_FAILURE_RATIO_THRESHOLD=0.5`

For a degraded cycle, inspect the associated `patient_publish_failed` entry and correct the underlying FHIR, database or networking problem. Restart the short-lived simulator task only after HAPI is healthy.

## Demo Shutdown and Cost Control

Stop the simulator immediately after validation or a recorded demo:

1. Run the following command block:

   ```zsh
   ./scripts/demo/stop_vitals_demo.sh
   ./scripts/demo/status_vitals_demo.sh
   ```

   The simulator is the intentionally short-lived Fargate workload. After evidence capture, complete the approved [controlled application teardown](infrastructure-lifecycle.md#controlled-application-teardown), which removes HAPI and the processing resources while retaining the protected state bucket and documented prerequisites. Stopping the simulator alone does not end infrastructure charges. Review CloudWatch logs, Fargate task count, network address translation (NAT) gateway usage, managed database size and retained object storage periodically when the environment is not being demonstrated.

## Evidence Handoff

Record the commit, CI result, Terraform convergence result, dashboard/alarm state and the outcome of REST and WebSocket checks. Keep the end-to-end, FHIR setup and load-test reports under `artifacts/e2e/` that serve as evidence. Redact all account-specific values and secrets before publishing portfolio evidence.
