# Healthcare Realtime Monitoring

An AWS portfolio project for synthetic realtime vital-sign monitoring. It ingests BIDMC waveform-derived measurements as FHIR observations, maintains current patient state for live clients, and builds governed analytical datasets for quality validation and reporting.

This repository uses synthetic Synthea data and waveform-derived measurements for demonstration only. It is not a clinical decision-support system and must not be used for patient care.

## What it demonstrates

- FHIR R4 observation ingestion through HAPI FHIR and a protected webhook.
- Kinesis-based realtime processing with latest-state delivery over IAM-authorized REST and WebSocket APIs.
- A Streamlit cohort dashboard designed to surface changes across multiple simulated patients.
- Durable raw landing, Glue/Iceberg processing, Athena validation, dbt models, Soda contracts, and OpenLineage events.
- Bounded replay through encrypted SQS failure queues and a replay Lambda.
- Terraform-managed AWS infrastructure, CloudWatch dashboards, alarms, and workload-scoped IAM roles.

## Architecture

The [architecture guide](docs/architecture.md) describes the realtime path, analytical path, recovery model, security boundaries, and observability design.

```text
Simulator -> HAPI FHIR -> webhook -> Kinesis -> Lambda -> DynamoDB -> REST/WebSocket dashboard
                                            \-> Firehose -> S3 -> Glue -> Athena -> dbt -> Soda
```

## Repository map

| Path | Contents |
| --- | --- |
| `infra/` | Terraform root and AWS service modules |
| `services/` | Webhook, realtime processor, API, replay, WebSocket, and simulator services |
| `dashboard/` | Streamlit cohort-monitoring client |
| `jobs/` | Glue and dbt runtime jobs |
| `airflow/` | MWAA Serverless workflow source and generator |
| `data_quality/` | Great Expectations and Soda validation assets |
| `lineage/` | OpenLineage event emitters |
| `scripts/` | Build, test-data, load-test, and demo helpers |
| `docs/` | Architecture, governance, operations, and demo documentation |

## Prerequisites

- macOS or a compatible Unix shell
- Python 3.12
- Terraform 1.11 or later
- AWS CLI authenticated to the target account
- Docker, when building ECS images locally
- An AWS environment provisioned from this repository

## Local setup

Clone the repository and create a local Python environment:

```zsh
cd healthcare-realtime-monitoring
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_dev.txt
.venv/bin/python -m pip install -r dashboard/requirements.txt
```

Create local configuration from the tracked examples. These files are ignored by Git and must contain values for your own AWS environment:

```zsh
cp .env.example .env
cp infra/development.tfvars.example infra/development.tfvars
```

Select the target AWS context before running AWS CLI, Terraform, or dashboard commands:

```zsh
export AWS_PROFILE="<aws-profile>"
export AWS_REGION="<aws-region>"
export AWS_DEFAULT_REGION="$AWS_REGION"
```

Do not commit secrets, deployment identifiers, Terraform state, signed headers, or generated workflow definitions.

## Validate the repository

```zsh
.venv/bin/python -m pytest tests scripts/synthea_loader/tests services/fhir_webhook/tests services/vitals_simulator/tests services/vitals_stream_processor/tests services/vitals_replay/tests services/vitals_api/tests services/websocket_handler/tests -q
.venv/bin/ruff check .
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
```

## Infrastructure workflow

Terraform configuration is intentionally environment-neutral. Review planned changes before every deployment:

```zsh
terraform -chdir=infra init
terraform -chdir=infra plan -var-file=development.tfvars
```

The detailed deployment, recovery, cost-control, and operational checks are in the [operations runbook](docs/operations-runbook.md).

## Run the dashboard

After the target environment is deployed, retrieve its endpoints from Terraform outputs and launch the local dashboard:

```zsh
export VITALS_API_ENDPOINT="$(terraform -chdir=infra output -raw vitals_api_endpoint)"
export VITALS_WEBSOCKET_URL="$(terraform -chdir=infra output -raw realtime_websocket_url)"
export PATIENT_IDS="<comma-separated-simulated-patient-ids>"
PYTHONPATH="$PWD" .venv/bin/python -m streamlit run dashboard/app.py
```

The dashboard uses AWS IAM credentials from the selected profile to sign REST and WebSocket requests. Keep the full cohort visible during a demo; focusing a patient should add context rather than hide the rest of the cohort.

## Demo and operations

Use the [demo guide](docs/demo-guide.md) for a complete live walkthrough, including startup, dashboard validation, Postman REST and WebSocket checks, CloudWatch review, and shutdown.

## Data governance

The [data governance guide](docs/data-governance.md) documents datasets, schema controls, quality gates, deduplication, retention, replay, and evidence expectations.

## Portfolio safety

Public artifacts must use placeholders for account IDs, buckets, endpoints, load balancers, local usernames, secrets, and signed headers. The project’s tracked examples are designed to be reproducible without revealing a deployed environment.
