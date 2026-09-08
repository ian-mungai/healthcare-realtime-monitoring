# Operations Runbook

## Scope

This runbook covers the portfolio demonstration environment. It uses synthetic data only. Do not use it as a clinical production procedure.

## Prerequisites

From any directory within a repository clone, select the AWS profile and region that host the target environment:

```zsh
cd "$(git rev-parse --show-toplevel)"
export AWS_PROFILE="<aws-profile>"
export AWS_REGION="<aws-region>"
```

Never place credentials, signed headers, account identifiers, endpoint identifiers, or secret values in shell history, screenshots, or public evidence.

Create the local Terraform input file from its tracked template, then replace every placeholder with values for the target AWS environment:

```zsh
cp infra/development.tfvars.example infra/development.tfvars
```

## CI and Deployment Gate

The CI workflow runs Python tests, linting, Terraform format and validation, generated-workflow validation, and container builds on pull requests and updates to `main`.

Before infrastructure deployment, run:

```zsh
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra plan -var-file=development.tfvars
```

Review every planned action. Apply only an approved saved plan. After deployment, repeat `terraform plan` and expect `No changes`.

## Demo Startup

Check current simulator state first:

```zsh
./scripts/demo/status_vitals_demo.sh
```

Start a single simulator task only when the status command reports it is stopped:

```zsh
./scripts/demo/start_vitals_demo.sh
```

The start script discovers the project network and task security group at runtime. It refuses to start a second simulator task for the same family.

## Live Validation

While the simulator is running, confirm all of the following:

- The cohort dashboard shows current values for all simulated patients.
- The live processing-latency and WebSocket-delivery alarms are `OK`.
- The REST vitals endpoint returns a current record using AWS IAM authorization.
- A Postman WebSocket connection authenticated with AWS IAM receives current patient updates.
- The current-state table advances event timestamps for the simulated cohort.

Use temporary Postman variables for endpoints and authorization. Do not export collections containing signed headers or private environment values.

## Incident Triage and Recovery

1. Check the two CloudWatch dashboards for processor errors, Kinesis iterator age, processing latency, and WebSocket delivery failures.
2. Check the simulator task status and its CloudWatch log stream.
3. Check the webhook Lambda log stream for authorization or secret-retrieval failures.
4. For processing failures, inspect the encrypted failure queue and replay dead-letter queue before redriving any message.
5. Correct the underlying data or deployment cause, then use the replay workflow only with a reviewed sequence range and a bounded replay attempt.
6. Verify fresh current-state records, dashboard updates, and alarm recovery before closing the incident.

### Simulator publication failures

The simulator isolates FHIR publication failures by patient. Retryable failures use bounded exponential backoff and reuse the same deterministic observation identifiers, so a partial retry does not create duplicate observations. Permanent failures are not retried.

Each cycle emits a structured summary with `status`, `patients_succeeded`, `patients_failed`, `failed_patient_ids`, and `consecutive_failed_cycles`. A single degraded cycle does not stop healthy patient streams. The task exits after three consecutive degraded cycles so a sustained HAPI or networking failure remains visible rather than running indefinitely in a failed state.

The deployed defaults are controlled by:

- `SIMULATOR_PUBLISH_MAX_ATTEMPTS=2`
- `SIMULATOR_PUBLISH_RETRY_BACKOFF_SECONDS=2`
- `SIMULATOR_MAX_CONSECUTIVE_FAILED_CYCLES=3`

For a degraded cycle, inspect the associated `patient_publish_failed` entry and correct the underlying FHIR, database, or networking problem. Restart the short-lived simulator task only after HAPI is healthy.

## Demo Shutdown and Cost Control

Stop the simulator immediately after validation or a recorded demo:

```zsh
./scripts/demo/stop_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

The simulator is the intentionally short-lived Fargate workload. Do not stop the HAPI service or data-processing resources as part of ordinary demo shutdown. Review CloudWatch logs, Fargate task count, NAT gateway usage, managed database size, and retained object storage periodically when the environment is not being demonstrated.

## Evidence Handoff

Record the commit, CI result, Terraform convergence result, dashboard/alarm state, and the outcome of REST and WebSocket checks. Redact all account-specific values and secrets before publishing portfolio evidence.
