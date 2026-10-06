---
title: "Demo Guide"
description: "Run a synthetic cohort demonstration and verify its observable results."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Demo Guide

For developers and operators: run a synthetic cohort demonstration and verify its observable results.

## Contents

- [Terminology](#terminology)
- [Before You Start](#before-you-start)
- [Goal](#goal)
- [Before the Demo](#before-the-demo)
- [Start the Simulator](#start-the-simulator)
- [Start the Dashboards](#start-the-dashboards)
- [Postman REST Check](#postman-rest-check)
- [Postman WebSocket Check](#postman-websocket-check)
- [CloudWatch Check](#cloudwatch-check)
- [Scripted Checks](#scripted-checks)
- [Analytics and Recovery Evidence](#analytics-and-recovery-evidence)
- [Shutdown](#shutdown)

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **CI**: continuous integration.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **IAM**: Identity and Access Management.
- **MWAA**: Managed Workflows for Apache Airflow.
- **REST**: Representational State Transfer.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Goal

Demonstrate that synthetic vital-sign events flow from the simulator through Fast Healthcare Interoperability Resources (FHIR), Kinesis, realtime serving, durable analytics and operational monitoring. Use only synthetic data and redact all environment-specific values from screenshots or recordings.

## Before the Demo

From the repository root, load the ignored target-environment settings:

1. Run the following command block:

   ```zsh
   set -a
   source "${PROJECT_ENV_FILE:-.env}"
   set +a
   ```

   Confirm the deployment is converged and that the simulator is not already running:

2. Run the following command block:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh --check
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-demo-check
   terraform -chdir=infra show -no-color tfplan-demo-check
   ./scripts/demo/status_vitals_demo.sh
   ```

   The Terraform plan should show no unexpected changes. Resolve infrastructure drift before a recorded demonstration.

## Start the Simulator

1. Run the following command block:

   ```zsh
   ./scripts/demo/start_vitals_demo.sh
   ./scripts/demo/status_vitals_demo.sh
   ```

   Wait until the task reports `RUNNING`. The script starts one Fargate simulator task and refuses to create another one while an existing task is active.

   In the simulator log stream, healthy cycles report `status=healthy`, `patients_succeeded=10` and `patients_failed=0`. Investigate any `status=degraded` cycle before using the run as release evidence.

   Task startup logs one `scenario_assigned` record per patient with a fresh encounter identifier and a `normal` or `deterioration_proxy` scenario. The startup log also states whether the run is planned to cover the full 30-minute window. The [scenario selector](analytics-star-schema.md#feature-and-label-construction) favors each patient's less frequent tagged scenario for those runs; ties and shorter planned runs use the seed or a random choice. Short planned runs do not count or add scenario-history tags.

   A realtime-only demonstration can remain short. For model-training rows, complete the full feature and outcome windows with observations in both. Two complete runs are an initial attempt to supply both classes; verify actual class diversity in both patient-grouped partitions and no patient leakage. Startup tags do not certify completed labels, so interrupted or concurrent runs can affect balancing.

## Start the Dashboards

Start the live cohort dashboard in its own terminal:

1. Run the following command block:

   ```zsh
   ./scripts/demo/start_live_dashboard.sh
   ```

   In the live dashboard, verify that:

   - [ ] The cohort view contains every configured simulated patient.
   - [ ] Heart rate, oxygen saturation, respiratory rate and blood pressure update while the simulator is running.
   - [ ] Heart rate, oxygen saturation and respiratory rate are no more than 10 seconds old; blood pressure follows its separate five-minute cadence and remains current for up to 310 seconds.
   - [ ] The chart time axis advances with full timestamps.
   - [ ] Selecting **View trends** focuses a patient without hiding the rest of the cohort.

   Start the separate model analytics dashboard in another terminal:

2. Run the following command block:

   ```zsh
   ./scripts/demo/start_model_analytics_dashboard.sh
   ```

   Confirm it shows the latest approved synthetic proxy score, feature-window vital summaries, encounter reference, freshness and model-governance labels for each scored patient. The launch scripts retrieve Terraform-created endpoints from outputs and analytical names from generated configuration, so do not copy those values into `.env`, documentation or screenshots.

## Postman REST Check

1. Create a temporary Postman environment with the following variables. Do not export it with deployed values.

   | Variable | Value |
   | --- | --- |
   | `aws_region` | Target AWS region |
   | `vitals_api_endpoint` | Terraform `vitals_api_endpoint` output |
   | `realtime_websocket_url` | Terraform `realtime_websocket_url` output, used by the WebSocket check |
   | `patient_id` | One simulated patient identifier |

2. Create a `GET` request:

   ```text
   {{vitals_api_endpoint}}/patients/{{patient_id}}/vitals
   ```

3. Configure AWS Signature authorization with service name `execute-api` and region `{{aws_region}}`.
4. Run the request twice during the demo.

Verify success by confirming that each returned vital's `<FIELD>_event_timestamp` advances, using the vital field names in the response. `<FIELD>` names the returned vital field, such as `heart_rate`.

## Postman WebSocket Check

1. Create a temporary WebSocket request in the same Postman environment:

   ```text
   {{realtime_websocket_url}}?patient_id={{patient_id}}
   ```

2. Configure AWS Identity and Access Management (IAM) signing for the target application programming interface (API) Gateway WebSocket connection.
3. Connect while the simulator is running.

Verify success by confirming that messages contain current measurements for the selected patient. Do not save signed authorization headers in a collection or evidence artifact; they are temporary credentials.

## CloudWatch Check

Read the two Terraform-managed dashboard names, then open them in the target AWS account:

1. Run the following command block:

   ```zsh
   terraform -chdir=infra output -raw realtime_observability_dashboard_name
   terraform -chdir=infra output -raw cloudwatch_dashboard_name
   ```

   | Dashboard | What to show |
   | --- | --- |
   | Realtime observability output | Current processing latency, Kinesis iterator age, processor errors, WebSocket delivery and simulator activity |
   | Pipeline observability output | Kinesis, Firehose, Glue, Managed Workflows for Apache Airflow (MWAA), dbt, Soda and end-to-end pipeline health |

   Confirm that the live processing-latency and WebSocket-delivery alarms are `OK`. The realtime dashboard should show fresh activity without sustained processor errors or an increasing iterator age.

## Scripted Checks

The REST, WebSocket, access-control and failure-handling checks above also run as scripted end-to-end scenarios that write a report for each run under `artifacts/e2e/`. Run them outside a recording, with the simulator stopped, because the realtime scenario starts its own simulator task:

1. Run the following command block:

   ```zsh
   .venv/bin/python -m e2e.run session
   ```

   The end-to-end test plan describes each scenario and its prerequisites.

## Analytics and Recovery Evidence

Before you start:

- Complete the deployed configuration and model approval prerequisites for the analytical workflow.
- Use the [model-training guide](model-training.md) when generating training data.

1. Run the simulator for at least 30 minutes when generating training data so each encounter covers both analytical windows.
2. Stop the simulator so Firehose can settle before processing a bounded cohort snapshot.
3. Start the analytical workflow through the selected environment's MWAA Serverless workflow.
4. Inspect the workflow and each Glue, Athena, Great Expectations, dbt, approved-model scoring, prediction-refresh and Soda task. Allow 30 minutes before checking the final state.
5. Inspect prediction freshness and OpenLineage validation. When `openlineage_collector_url` is nonempty, inspect matching START and COMPLETE events for the same run IDs in the shared collector.

Verify success by confirming that the workflow, each task, prediction freshness and lineage validation report success. Elapsed time alone does not establish completion. Scenario assignment does not guarantee both labels in both patient-grouped partitions; repeat a complete training run only when the dbt readiness test reports a missing class.

Do not intentionally inject a production-style failure during a portfolio recording. If recovery evidence is needed, use the report from the replay scenario, which blocks writes for one synthetic patient outside the cohort or follow the controlled replay procedure in the [operations runbook](operations-runbook.md).

## Shutdown

Stop the short-lived simulator task as soon as the demonstration is complete:

1. Run the following command block:

   ```zsh
   ./scripts/demo/stop_vitals_demo.sh
   ./scripts/demo/status_vitals_demo.sh
   ```

   Record the commit, continuous integration (CI) result, Terraform convergence result, dashboard and alarm status and REST/WebSocket outcomes. Redact account-specific values and secrets before sharing the evidence.

   Complete the approved [controlled application teardown](infrastructure-lifecycle.md#controlled-application-teardown) after evidence capture. Stopping the simulator alone leaves billable infrastructure running.
