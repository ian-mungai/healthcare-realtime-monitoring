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

### Patient access policy

Before deployment, configure `realtime_patient_access_policy` in the ignored `infra/development.tfvars` file. Each key is an IAM principal ARN pattern and each value lists the patient ID patterns that principal may read or subscribe to:

```hcl
realtime_patient_access_policy = {
  "arn:aws:iam::<aws-account-id>:user/<dashboard-user>"      = ["<patient-id-1>", "<patient-id-2>"]
  "arn:aws:sts::<aws-account-id>:assumed-role/<role-name>/*" = ["<patient-id-1>", "<patient-id-2>", "load_test_patient_*"]
}
```

The default empty policy denies all patient access. Use an exact IAM user ARN or a narrowly scoped assumed-role session pattern; do not use a wildcard principal. Add `load_test_patient_*` only for principals that run the isolated load test.

All supported FHIR webhook routes require `X-Webhook-Secret`, including health, metadata, and subscription handshake requests. The Lambda refreshes its cached Secrets Manager value within five minutes, so secret rotation does not require a cold start.

Create the local Terraform input file from its tracked template, then replace every placeholder with values for the target AWS environment:

```zsh
cp infra/development.tfvars.example infra/development.tfvars
```

### Terraform state

Use the project's private, versioned data bucket for Terraform state. The backend example isolates state under the `terraform-state/development/` prefix; copy it and set the project bucket and region for the target environment:

```zsh
cp infra/backend.hcl.example infra/backend.hcl
```

For a new checkout, initialize with the remote backend:

```zsh
terraform -chdir=infra init -backend-config=backend.hcl
```

For an existing deployment that still has local state, migrate it once:

```zsh
terraform -chdir=infra init -backend-config=backend.hcl -migrate-state
```

Confirm that the state object exists in the configured bucket before removing any local state backup. S3 versioning provides recovery and Terraform's `use_lockfile` setting provides native locking.

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

### Analytical quarantine recovery

Inspect rejected rows through Athena before replaying anything:

```sql
SELECT rejection_reason, count(*) AS rejected_rows
FROM healthcare_realtime.quarantined_fhir_observations
GROUP BY rejection_reason
ORDER BY rejected_rows DESC;
```

Export a bounded reason group to local JSONL, correct the rejected fields, and validate the file without publishing:

```zsh
export DATA_BUCKET="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"
export VITALS_STREAM="$(terraform -chdir=infra output -raw kinesis_stream_name)"

.venv/bin/python scripts/quarantine/manage_quarantine.py --region "$AWS_REGION" export \
  --bucket "$DATA_BUCKET" \
  --rejection-reason "<rejection-reason>" \
  --output tmp/quarantine-review.jsonl

.venv/bin/python scripts/quarantine/manage_quarantine.py --region "$AWS_REGION" replay \
  --input tmp/quarantine-review.jsonl \
  --stream-name "$VITALS_STREAM"
```

Review the validated count, then publish the corrected rows by repeating the replay command with `--confirm-replay`. Replayed rows retain the original observation ID, use `source=quarantine_replay`, pass through Firehose and Glue again, and remain idempotent at the analytical `(observation_id, loinc_code)` grain.

### Simulator publication failures

The simulator isolates FHIR publication failures by patient. The HAPI client owns the single bounded retry policy and reuses deterministic observation identifiers, so partial retries do not create duplicate observations. Patients with permanent failures are disabled for the remainder of the task while healthy patient streams continue.

Each cycle emits a structured summary with `status`, patient counts, disabled patients, the retryable failure ratio, and consecutive systemic failure cycles. The task exits only when retryable failures meet the configured cohort ratio for three consecutive cycles. Cycle overruns and patient publication failures publish CloudWatch metrics from structured log entries and notify through the project alert topic.

The deployed defaults are controlled by:

- `SIMULATOR_FHIR_MAX_ATTEMPTS=2`
- `SIMULATOR_FHIR_RETRY_BACKOFF_SECONDS=2`
- `SIMULATOR_MAX_CONSECUTIVE_FAILED_CYCLES=3`
- `SIMULATOR_FAILURE_RATIO_THRESHOLD=0.5`

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
