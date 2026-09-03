# Demo Guide

## Goal

Demonstrate that synthetic vital-sign events flow from the simulator through FHIR, Kinesis, realtime serving, durable analytics, and operational monitoring. Use only synthetic data and redact all environment-specific values from screenshots or recordings.

## Before the demo

From the repository root, select the target AWS profile and region:

```zsh
export AWS_PROFILE="<aws-profile>"
export AWS_REGION="<aws-region>"
export AWS_DEFAULT_REGION="$AWS_REGION"
```

Confirm the deployment is converged and that the simulator is not already running:

```zsh
terraform -chdir=infra plan -var-file=development.tfvars
./scripts/demo/status_vitals_demo.sh
```

The Terraform plan should show no unexpected changes. Resolve infrastructure drift before a recorded demonstration.

## Start the simulator

```zsh
./scripts/demo/start_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

Wait until the task reports `RUNNING`. The script starts one Fargate simulator task and refuses to create another one while an existing task is active.

## Start the dashboard

Retrieve the target endpoints without copying them into documentation or screenshots:

```zsh
export VITALS_API_ENDPOINT="$(terraform -chdir=infra output -raw vitals_api_endpoint)"
export VITALS_WEBSOCKET_URL="$(terraform -chdir=infra output -raw realtime_websocket_url)"
export PATIENT_IDS="<comma-separated-simulated-patient-ids>"
PYTHONPATH="$PWD" .venv/bin/python -m streamlit run dashboard/app.py
```

In the dashboard, verify that:

1. The cohort view contains every configured simulated patient.
2. Heart rate, oxygen saturation, respiratory rate, and blood pressure update while the simulator is running.
3. The chart time axis advances with full timestamps.
4. Selecting **View trends** focuses a patient without hiding the rest of the cohort.
5. Returning to cohort view clears the focus while retaining all patient lines.

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
| `healthcare-realtime-live-development` | Current processing latency, Kinesis iterator age, processor errors, WebSocket delivery, and simulator activity |
| `healthcare-realtime-monitoring` | Kinesis, Firehose, Glue, MWAA, dbt, Soda, and end-to-end pipeline health |

Confirm that the live processing-latency and WebSocket-delivery alarms are `OK`. The realtime dashboard should show fresh activity without sustained processor errors or an increasing iterator age.

## Analytics and recovery evidence

For an extended demonstration, show a successful MWAA workflow run and its Glue, Athena, dbt, and Soda tasks. Then confirm that Great Expectations, Soda contracts, and OpenLineage events have completed successfully.

Do not intentionally inject a production-style failure during a portfolio recording. If recovery evidence is needed, use a reviewed synthetic failure case and follow the controlled replay procedure in the [operations runbook](operations-runbook.md).

## Shutdown

Stop the short-lived simulator task as soon as the demonstration is complete:

```zsh
./scripts/demo/stop_vitals_demo.sh
./scripts/demo/status_vitals_demo.sh
```

Record the commit, CI result, Terraform convergence result, dashboard and alarm status, and REST/WebSocket outcomes. Redact account-specific values and secrets before sharing the evidence.
