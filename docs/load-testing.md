---
title: "Realtime Load Testing"
description: "Measure isolated throughput and delivery latency with repeatable local reports."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Realtime Load Testing

For developers and operators: measure isolated throughput and delivery latency with repeatable local reports.

## Contents

- [Terminology](#terminology)
- [Before You Start](#before-you-start)
- [Scope](#scope)
- [Deploy the Isolated Lane](#deploy-the-isolated-lane)
- [Run an End-to-End Test](#run-an-end-to-end-test)
- [E2E Artifact](#e2e-artifact)
- [Cleanup and Safeguards](#cleanup-and-safeguards)
- [Artifact Path Placeholders](#artifact-path-placeholders)

## Terminology

- **E2E**: end-to-end.
- **AWS**: Amazon Web Services.
- **CLI**: command-line interface.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **HTTP**: Hypertext Transfer Protocol.
- **JSON**: JavaScript Object Notation.
- **TTL**: time to live.
- **URL**: uniform resource locator.
- **UTC**: Coordinated Universal Time.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or AWS commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Scope

The realtime load test uses a dedicated Kinesis stream and DynamoDB results table. The test stream is not connected to Firehose, so test events do not enter the raw S3, Glue, Iceberg, Athena or dbt paths. The processor stores each test observation separately, delivers it to subscribed WebSocket clients and publishes test metrics under `HealthcareRealtime/LoadTest` rather than the live namespace.

## Deploy the Isolated Lane

Build the realtime processor Lambda package, review the Terraform plan and apply it using the configuration for your environment:

1. Run the following command block:

   ```zsh
   set -a
   source "${PROJECT_ENV_FILE:-.env}"
   set +a

   scripts/lambda/build_vitals_stream_processor.sh
   ./scripts/infrastructure/render_project_config.sh --check
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-load-test
   terraform -chdir=infra show -no-color tfplan-load-test
   ```

   Review the preceding plan or cleanup preview. Obtain approval for its exact changes before running the next action. Stop on unexpected deletion, replacement or permission changes.

2. Apply only the reviewed and approved action:

   ```zsh
   terraform -chdir=infra apply tfplan-load-test
   ```

   The plan should add the isolated stream, results table, processor event-source mapping and related least-privilege permissions. It should not attach the test stream to Firehose.

## Run an End-to-End Test

Prerequisites:

- A deployed isolated lane and a generated ten-patient Fast Healthcare Interoperability Resources (FHIR) map from that deployment.
- Stopped simulator traffic and closed ordinary dashboard subscribers.
- Agreed latency thresholds if the run is intended to establish a performance pass.

The map supplies both event payloads and subscriptions. Load-test events write the isolated results table rather than the cohort's latest-vitals table. The dashboard ignores events whose `source` is `load_test`. Close ordinary subscribers for the documented measurement baseline; this removes their additional WebSocket delivery traffic.

1. Retrieve the deployed names and run the test:

   ```zsh
   export VITALS_WEBSOCKET_URL="$(terraform -chdir=infra output -raw realtime_websocket_url)"
   export KINESIS_STREAM_NAME="$(terraform -chdir=infra output -raw kinesis_stream_name)"
   export LOAD_TEST_KINESIS_STREAM_NAME="$(terraform -chdir=infra output -raw load_test_kinesis_stream_name)"
   export LOAD_TEST_RESULTS_TABLE="$(terraform -chdir=infra output -raw load_test_results_table_name)"

   .venv/bin/python -m scripts.load_testing.realtime_load_test \
     --stream-name "$LOAD_TEST_KINESIS_STREAM_NAME" \
     --results-table "$LOAD_TEST_RESULTS_TABLE" \
     --websocket-url "$VITALS_WEBSOCKET_URL" \
     --patients 10 \
     --events-per-second 1 \
     --duration-seconds 60
   ```

   The runner reads `KINESIS_STREAM_NAME` so it can refuse to write to the production stream. The command fails if an accepted observation does not reach DynamoDB or a subscribed WebSocket within the timeout. It reports Kinesis request latency, Kinesis-to-DynamoDB processing latency and Kinesis-to-WebSocket delivery latency.

2. Inspect the report and verify accepted observations, zero producer failures and no missing requested DynamoDB or WebSocket observations. Compare latency percentiles with the agreed thresholds before claiming a performance pass.

The default map is `scripts/synthea_loader/state/fhir_resource_map.json`. Set `FHIR_RESOURCE_MAP_FILE` or pass `--patient-map` for another map from the selected deployment. The map must contain ten unique cohort patient identifiers. Select between one and ten patients with `--patients`; increase `--events-per-second` for higher load rather than inventing patient identifiers outside the access policy. Missing or invalid inputs fail before submitting events. CLI help works without private deployment inputs:

```zsh
.venv/bin/python -m scripts.load_testing.realtime_load_test --help
```

The default run attempts about 600 events: ten patients, one event per second per patient and sixty seconds. A delivery pass requires accepted observations, zero producer failures and no missing requested DynamoDB or WebSocket observations. Define latency acceptance thresholds before claiming a performance pass; the runner records percentiles but does not enforce a latency target.

## E2E Artifact

Every run, passed or failed, writes `report.json` and `report.md` to `artifacts/e2e/load_test/<UTC_TIME>_<RUN_ID>/`. They record the code revision (and whether tracked files had uncommitted changes), the parameters, cohort-map hash, producer, DynamoDB and WebSocket results with latency percentiles, the pass or fail status and sanitized error and the run's limits. Patient identifiers, deployment names, the WebSocket URL and signed headers are never written. Use `--artifact-dir` to choose another folder. Review a report before using it as local release evidence. Keep reports ignored and outside Git and release archives.

WebSocket delivery is labeled verified only when the run passes and the observed count matches every accepted producer write with none missing. A failed connection or absent metrics is not verified; an explicitly skipped check is labeled skipped. The CLI exits nonzero on failure. Preserve previous failed reports when preparing or rerunning fixes.

A failed run records `error_category` and an `error` that starts with the same category:

- `configuration`: a missing or invalid setting or flag.
- `cohort map`: the map is missing, unreadable, invalid or changed during the read.
- `websocket access`: missing credentials or subscriptions that did not connect, with the handshake HTTP status when there is one.
- `producer`, `delivery` or `cleanup`: failed writes, missing observations or connections that did not close.
- `aws request` or `unexpected`: the AWS error code or the exception type only.

Error messages are fixed text and counts; they never include identifiers, resource names or service error messages.

Each parsed load-test invocation receives a unique run identifier, including prerequisite failures. Help and argument-parser exits do not create a report. Rejected non-finite rate or timeout inputs are recorded as `null`, so failed artifacts remain valid JSON.

## Cleanup and Safeguards

The runner deletes only observation IDs created by its current run. The processor sets a 24-hour expiry for results. DynamoDB time to live (TTL) deletes expired rows asynchronously, so abandoned results can remain after expiry; see the [AWS TTL documentation](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html). WebSocket connections close at the end of the run; the production Kinesis stream is explicitly rejected by the runner.

Use `--retain-results` only when temporary DynamoDB evidence is required. Use `--skip-websocket` only for a deliberately limited processor test; it does not validate the complete realtime delivery path.

## Artifact Path Placeholders

- `<UTC_TIME>`: UTC timestamp generated by the runner.
- `<RUN_ID>`: unique run identifier generated by the runner.

These path components are output labels; you do not enter them as deployment inputs.
