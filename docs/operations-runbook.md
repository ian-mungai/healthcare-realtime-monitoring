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

## Demo Shutdown and Cost Control

Stop the simulator immediately after validation or a recorded demo:

```zsh
./scripts/demo/stop_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

The simulator is the intentionally short-lived Fargate workload. Do not stop the HAPI service or data-processing resources as part of ordinary demo shutdown. Review CloudWatch logs, Fargate task count, NAT gateway usage, managed database size, and retained object storage periodically when the environment is not being demonstrated.

## Evidence Handoff

Record the commit, CI result, Terraform convergence result, dashboard/alarm state, and the outcome of REST and WebSocket checks. Redact all account-specific values and secrets before publishing portfolio evidence.
