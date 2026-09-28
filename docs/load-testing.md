# Realtime Load Testing

The realtime load test uses a dedicated Kinesis stream and DynamoDB results table. The test stream is not connected to Firehose, so test events do not enter the raw S3, Glue, Iceberg, Athena or dbt paths. The processor stores each test observation separately, delivers it to subscribed WebSocket clients and publishes test metrics under `HealthcareRealtime/LoadTest` rather than the live namespace.

## Deploy the isolated lane

Build the realtime processor Lambda package, review the Terraform plan and apply it using the configuration for your environment:

```zsh
cd healthcare-realtime-monitoring
set -a
source .env
set +a

scripts/lambda/build_vitals_stream_processor.sh
./scripts/infrastructure/render_project_config.sh --check
terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-load-test
terraform -chdir=infra show -no-color tfplan-load-test
terraform -chdir=infra apply tfplan-load-test
```

The plan should add the isolated stream, results table, processor event-source mapping and related least-privilege permissions. It should not attach the test stream to Firehose.

## Run an end-to-end test

Retrieve the deployed names instead of copying environment-specific identifiers into commands:

```zsh
export VITALS_WEBSOCKET_URL="$(terraform -chdir=infra output -raw realtime_websocket_url)"
export KINESIS_STREAM_NAME="$(terraform -chdir=infra output -raw kinesis_stream_name)"
export LOAD_TEST_KINESIS_STREAM_NAME="$(terraform -chdir=infra output -raw load_test_kinesis_stream_name)"
export LOAD_TEST_RESULTS_TABLE="$(terraform -chdir=infra output -raw load_test_results_table_name)"

.venv/bin/python scripts/load_testing/realtime_load_test.py \
  --stream-name "$LOAD_TEST_KINESIS_STREAM_NAME" \
  --results-table "$LOAD_TEST_RESULTS_TABLE" \
  --websocket-url "$VITALS_WEBSOCKET_URL" \
  --patients 10 \
  --events-per-second 1 \
  --duration-seconds 60
```

The runner reads `KINESIS_STREAM_NAME` so it can refuse to write to the production stream. The command fails if an accepted observation does not reach DynamoDB or a subscribed WebSocket within the timeout. It reports Kinesis request latency, Kinesis-to-DynamoDB processing latency and Kinesis-to-WebSocket delivery latency.

## E2E artifact

Every run, passed or failed, writes `report.json` and `report.md` to `artifacts/e2e/load_test/<UTC time>_<run id>/`. They record the code revision (and whether tracked files had uncommitted changes), the parameters, producer, DynamoDB and WebSocket results with latency percentiles, the pass or fail status and error, and the run's limits. The WebSocket URL is never written. Use `--artifact-dir` to choose another folder. Review a report before committing it as release evidence.

## Cleanup and safeguards

The runner deletes only observation IDs created by its current run. DynamoDB TTL removes abandoned results after 24 hours if the process is interrupted. WebSocket connections close at the end of the run; the production Kinesis stream is explicitly rejected by the runner.

Use `--retain-results` only when temporary DynamoDB evidence is required. Use `--skip-websocket` only for a deliberately limited processor test; it does not validate the complete realtime delivery path.
