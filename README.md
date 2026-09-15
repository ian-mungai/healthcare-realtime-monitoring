# Healthcare Realtime Monitoring

An AWS portfolio project for synthetic realtime vital-sign monitoring. It ingests BIDMC waveform-derived measurements as FHIR observations, maintains current patient state for live clients, and builds governed analytical datasets for quality validation and reporting.

This repository uses synthetic Synthea data and waveform-derived measurements for demonstration only. It is not a clinical decision-support system and must not be used for patient care.

## What it demonstrates

- FHIR R4 observation ingestion through HAPI FHIR and a protected webhook.
- Kinesis-based realtime processing with latest-state delivery over IAM-authorized REST and WebSocket APIs.
- A Streamlit cohort dashboard designed to surface changes across multiple simulated patients.
- Durable normalized-event landing, Glue/Iceberg processing, Athena validation, dbt models, automated approved-model scoring, Soda contracts, and OpenLineage events collected by IAM-protected Marquez or stored in S3.
- Bounded replay through encrypted SQS failure queues and a replay Lambda.
- Terraform-managed AWS infrastructure, CloudWatch dashboards, alarms, and workload-scoped IAM roles.

## Architecture

The [architecture guide](docs/architecture.md) describes the realtime path, analytical path, recovery model, security boundaries, and observability design.

```text
Simulator -> HAPI FHIR -> webhook -> Kinesis -> Lambda -> DynamoDB -> REST/WebSocket dashboard
                                            \-> Firehose -> S3 -> Glue -> Athena -> dbt -> ML scoring -> Soda
```

## Repository map

| Path | Contents |
| --- | --- |
| `infra/` | Terraform root and AWS service modules |
| `services/` | Webhook, realtime processor, API, replay, WebSocket, and simulator services |
| `dashboard/` | Streamlit cohort-monitoring client |
| `jobs/` | Glue, dbt, and machine-learning runtime jobs |
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
- Java 17 and Gradle, when generating Synthea data
- Power BI Desktop and the Amazon Athena ODBC driver, only for the optional reporting connection
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

Infrastructure and demo scripts load missing values from the ignored `.env`; variables already exported in the shell take precedence. Complete the tracked placeholders, then verify local, AWS, GitHub, state, secret, IAM, OIDC, SNS, and Docker prerequisites:

```zsh
./scripts/infrastructure/check_prerequisites.sh
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
.venv/bin/ruff format --check .
.venv/bin/python -m mypy .
for contract in data_quality/soda/contracts/*.yml; do .venv/bin/soda contract test --contract "$contract"; done
PYTHONPATH="$PWD/airflow/serverless:$PWD/airflow/dags:$PWD" .venv/bin/python -m unittest discover -s airflow/serverless/tests -v
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
```

## Infrastructure workflow

Terraform uses a partial S3 backend configuration with native state locking. The protected bootstrap stack creates a private, versioned bucket that is separate from application data and survives application teardown:

```zsh
cp infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars
./scripts/infrastructure/bootstrap.sh state-plan
```

Review and apply the bootstrap plan, run `./scripts/infrastructure/bootstrap.sh state-backup`, then run `./scripts/infrastructure/bootstrap.sh main-init`. For an existing environment, use the guarded `main-migrate` action documented in the lifecycle guide. Bootstrap inputs, backend configuration, and state files are ignored by Git.

The [bootstrap guide](docs/bootstrap.md) covers first deployment. The [infrastructure lifecycle guide](docs/infrastructure-lifecycle.md) covers persistent state, guarded teardown, and recreation. The [external prerequisite inventory](docs/external-prerequisites.md) identifies account configuration outside the application stack. The [deployment guide](docs/deployment.md) covers GitHub OIDC and shared OpenLineage collector setup. Recovery, cost-control, and operational checks are in the [operations runbook](docs/operations-runbook.md).

## Run the dashboard

After the target environment is deployed, retrieve its endpoints from Terraform outputs and launch the local dashboard:

```zsh
export VITALS_API_ENDPOINT="$(terraform -chdir=infra output -raw vitals_api_endpoint)"
export VITALS_WEBSOCKET_URL="$(terraform -chdir=infra output -raw realtime_websocket_url)"
export DATA_BUCKET_NAME="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"
export PATIENT_IDS="<comma-separated-simulated-patient-ids>"
PYTHONPATH="$PWD" .venv/bin/python -m streamlit run dashboard/app.py
```

The dashboard uses AWS IAM credentials from the selected profile to sign REST and WebSocket requests. Keep the full cohort visible during a demo; focusing a patient should add context rather than hide the rest of the cohort.

## Demo and operations

Use the [demo guide](docs/demo-guide.md) for a complete live walkthrough, including startup, dashboard validation, Postman REST and WebSocket checks, CloudWatch review, and shutdown.

Use the [load-testing guide](docs/load-testing.md) to run an isolated test that measures Kinesis-to-DynamoDB processing and WebSocket delivery latency without writing test events into the analytical lakehouse.

## Data governance

The [data governance guide](docs/data-governance.md) documents datasets, schema controls, quality gates, deduplication, retention, replay, and evidence expectations.

The [analytics star schema](docs/analytics-star-schema.md) defines the observation fact grain, conformed dimensions, key strategy, legacy encounter handling, and bus matrix.

The [model-training guide](docs/model-training.md) defines the inference-safe training windows and reproducible logistic-regression baseline. The [model-predictions guide](docs/model-predictions.md) covers daily approved-model scoring and Athena presentation datasets. The [Power BI connection guide](docs/power-bi-connection.md) stops after connecting Power BI to Athena; report construction is intentionally out of scope.

The [technology inventory](docs/technology-inventory.md) lists the standards, AWS services, frameworks, libraries, delivery tools, and testing methods used by the project.

## Portfolio safety

Public artifacts must use placeholders for account IDs, buckets, endpoints, load balancers, local usernames, secrets, and signed headers. The project’s tracked examples are designed to be reproducible without revealing a deployed environment.
