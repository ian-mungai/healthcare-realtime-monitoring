# Demo Guide

## Goal

Demonstrate that synthetic vital-sign events flow from the simulator through FHIR, Kinesis, realtime serving, durable analytics and operational monitoring. Use only synthetic data and redact all environment-specific values from screenshots or recordings.

## Before the demo

From the repository root, load the ignored target-environment settings:

```zsh
set -a
source .env
set +a
```

Confirm the deployment is converged and that the simulator is not already running:

```zsh
./scripts/infrastructure/render_project_config.sh --check
terraform -chdir=infra plan -out=tfplan-demo-check
terraform -chdir=infra show -no-color tfplan-demo-check
./scripts/demo/status_vitals_demo.sh
```

The Terraform plan should show no unexpected changes. Resolve infrastructure drift before a recorded demonstration.

## Start the simulator

```zsh
./scripts/demo/start_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

Wait until the task reports `RUNNING`. The script starts one Fargate simulator task and refuses to create another one while an existing task is active.

In the simulator log stream, healthy cycles report `status=healthy`, `patients_succeeded=10` and `patients_failed=0`. Investigate any `status=degraded` cycle before using the run as release evidence.

Task startup logs one `scenario_assigned` record per patient with a fresh encounter identifier and a randomly selected `normal` or `deterioration_proxy` scenario. A realtime-only demonstration can remain short. A run intended to create model-training rows must continue for at least 30 minutes so every encounter has a complete feature window and outcome window.

## Start the dashboards

Start the live cohort dashboard in its own terminal:

```zsh
./scripts/demo/start_live_dashboard.sh
```

In the live dashboard, verify that:

1. The cohort view contains every configured simulated patient.
2. Heart rate, oxygen saturation, respiratory rate and blood pressure update while the simulator is running.
3. Heart rate, oxygen saturation and respiratory rate are no more than 10 seconds old; blood pressure follows its separate five-minute cadence and remains current for up to 310 seconds.
4. The chart time axis advances with full timestamps.
5. Selecting **View trends** focuses a patient without hiding the rest of the cohort.

Start the separate model analytics dashboard in another terminal:

```zsh
./scripts/demo/start_model_analytics_dashboard.sh
```

Confirm it shows the latest approved synthetic proxy score, feature-window vital summaries, encounter reference, freshness and model-governance labels for each scored patient. The launch scripts retrieve Terraform-created endpoints from outputs and analytical names from generated configuration, so do not copy those values into `.env`, documentation or screenshots.

## Postman REST check

Create a temporary Postman environment with the following variables. Do not export it with deployed values.

| Variable | Value |
| --- | --- |
| `aws_region` | Target AWS region |
| `vitals_api_endpoint` | Terraform `vitals_api_endpoint` output |
| `patient_id` | One simulated patient identifier |

Create a `GET` request:

```text
{{vitals_api_endpoint}}/patients/{{patient_id}}/vitals
```

Configure the request for AWS Signature authorization with service name `execute-api` and region `{{aws_region}}`. Run it twice during the demo and confirm that the returned event timestamp advances.

## Postman WebSocket check

Create a temporary WebSocket request:

```text
{{realtime_websocket_url}}?patient_id={{patient_id}}
```

Use AWS IAM signing for the target API Gateway WebSocket connection. Connect while the simulator is running, then confirm that messages contain current measurements for the selected patient. Do not save signed authorization headers in a collection or evidence artifact; they are temporary credentials.

## CloudWatch check

Open the two Terraform-managed dashboards in the target AWS account:

| Dashboard | What to show |
| --- | --- |
| `healthcare-realtime-live-development` | Current processing latency, Kinesis iterator age, processor errors, WebSocket delivery and simulator activity |
| `healthcare-realtime-monitoring` | Kinesis, Firehose, Glue, MWAA, dbt, Soda and end-to-end pipeline health |

Confirm that the live processing-latency and WebSocket-delivery alarms are `OK`. The realtime dashboard should show fresh activity without sustained processor errors or an increasing iterator age.

## Analytics and recovery evidence

For an extended demonstration, show a successful MWAA workflow run and its Glue, Athena, Great Expectations, dbt, approved-model scoring, prediction refresh and Soda tasks. Confirm that prediction freshness and OpenLineage validation completed successfully. When the `openlineage_collector_url` Terraform output is nonempty, confirm the shared collector contains matching START and COMPLETE events for the same run IDs.

For training-data generation, let the simulator run for at least 30 minutes before stopping it. Random scenarios do not guarantee that one run supplies both labels to both patient-grouped partitions. Repeat the complete run only when the dbt readiness test reports a missing class.

Stop the simulator before starting the analytical workflow so Firehose can settle and the run processes a bounded cohort snapshot. After starting MWAA Serverless, wait 30 minutes before checking the final state; recent runs have taken 26 to 28 minutes.

Do not intentionally inject a production-style failure during a portfolio recording. If recovery evidence is needed, use a reviewed synthetic failure case and follow the controlled replay procedure in the [operations runbook](operations-runbook.md).

## Shutdown

Stop the short-lived simulator task as soon as the demonstration is complete:

```zsh
./scripts/demo/stop_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

Record the commit, CI result, Terraform convergence result, dashboard and alarm status and REST/WebSocket outcomes. Redact account-specific values and secrets before sharing the evidence.
