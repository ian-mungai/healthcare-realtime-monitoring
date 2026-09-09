# Realtime Load Testing

The realtime load test uses a dedicated Kinesis stream and DynamoDB results table. The test stream is not connected to Firehose, so test events do not enter the raw S3, Glue, Iceberg, Athena, or dbt paths. The processor stores each test observation separately, delivers it to subscribed WebSocket clients, and publishes test metrics under `HealthcareRealtime/LoadTest` rather than the live namespace.

## Deploy the isolated lane

Build the realtime processor Lambda package, review the Terraform plan, and apply it using the configuration for your environment:

```zsh
cd healthcare-realtime-monitoring
export AWS_PROFILE="<aws-profile>"
export AWS_REGION="<aws-region>"
export AWS_DEFAULT_REGION="$AWS_REGION"

scripts/lambda/build_vitals_stream_processor.sh
terraform -chdir=infra plan -var-file=development.tfvars
terraform -chdir=infra apply -var-file=development.tfvars
```

The plan should add the isolated stream, results table, processor event-source mapping, and related least-privilege permissions. It should not attach the test stream to Firehose.

## Run an end-to-end test

Retrieve the deployed names instead of copying environment-specific identifiers into commands:

```zsh
export VITALS_WEBSOCKET_URL="$(terraform -chdir=infra output -raw realtime_websocket_url)"
export LOAD_TEST_STREAM="$(terraform -chdir=infra output -raw load_test_kinesis_stream_name)"
export LOAD_TEST_RESULTS_TABLE="$(terraform -chdir=infra output -raw load_test_results_table_name)"

.venv/bin/python scripts/load_testing/realtime_load_test.py \
  --stream-name "$LOAD_TEST_STREAM" \
  --results-table "$LOAD_TEST_RESULTS_TABLE" \
  --websocket-url "$VITALS_WEBSOCKET_URL" \
  --patients 10 \
  --events-per-second 1 \
  --duration-seconds 60
```

The command fails if an accepted observation does not reach DynamoDB or a subscribed WebSocket within the timeout. It reports Kinesis request latency, Kinesis-to-DynamoDB processing latency, and Kinesis-to-WebSocket delivery latency.

## Cleanup and safeguards

The runner deletes only observation IDs created by its current run. DynamoDB TTL removes abandoned results after 24 hours if the process is interrupted. WebSocket connections close at the end of the run, and the production Kinesis stream is explicitly rejected by the runner.

Use `--retain-results` only when temporary DynamoDB evidence is required. Use `--skip-websocket` only for a deliberately limited processor test; it does not validate the complete realtime delivery path.
