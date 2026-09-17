# Healthcare Realtime Monitoring

An AWS portfolio project for synthetic realtime vital-sign monitoring. It ingests BIDMC waveform-derived measurements as FHIR observations, maintains current patient state for live clients and builds governed analytical datasets for quality validation and reporting.

This repository uses synthetic Synthea data and waveform-derived measurements for demonstration only. It is not a clinical decision-support system and must not be used for patient care.

## What it demonstrates

- FHIR R4 observation ingestion through HAPI FHIR and a protected webhook.
- Kinesis-based realtime processing with latest-state delivery over IAM-authorized REST and WebSocket APIs.
- Separate Streamlit dashboards for live cohort monitoring and approved-model analytics.
- Durable normalized-event landing, Glue/Iceberg processing, Athena validation, dbt models, automated approved-model scoring, Soda contracts and OpenLineage events collected by IAM-protected Marquez or stored in S3.
- Bounded replay through encrypted SQS failure queues and a replay Lambda.
- Terraform-managed AWS infrastructure, CloudWatch dashboards, alarms and workload-scoped IAM roles.

## Architecture

The [architecture guide](docs/architecture.md) describes the realtime path, analytical path, recovery model, security boundaries and observability design.

```text
Simulator -> HAPI FHIR -> webhook -> Kinesis -> Lambda -> DynamoDB -> REST/WebSocket -> live cohort dashboard
                                            \-> Firehose -> S3 -> Glue -> Athena -> dbt -> ML scoring -> model analytics dashboard
                                                                                         \-> Soda
```

## Repository map

| Path | Contents |
| --- | --- |
| `infra/` | Terraform root and AWS service modules |
| `services/` | Webhook, realtime processor, API, replay, WebSocket and simulator services |
| `dashboard/` | Streamlit live cohort and model analytics clients |
| `jobs/` | Glue, dbt and machine-learning runtime jobs |
| `airflow/` | MWAA Serverless workflow source and generator |
| `data_quality/` | Great Expectations and Soda validation assets |
| `lineage/` | OpenLineage event emitters |
| `scripts/` | Build, test-data, load-test and demo helpers |
| `docs/` | Architecture, governance, operations, demo and Power BI connection documentation |

## Prerequisites

- macOS or a compatible Unix shell
- Python 3.12
- Terraform 1.11 or later
- AWS CLI authenticated to the target account
- A temporary administrator or approved bootstrap identity for first deployment
- Docker, when building ECS images locally
- Java 17 and Gradle, when generating Synthea data
- Power BI Desktop and the Amazon Athena ODBC driver, only when reproducing the completed reporting connection

## Local setup

Clone the repository and create a local Python environment:

```zsh
cd healthcare-realtime-monitoring
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_dev.txt
```

Create the one ignored local configuration file:

```zsh
cp .env.example .env
```

Complete the placeholders in `.env`, then render both Terraform inputs:

```zsh
./scripts/infrastructure/render_project_config.sh
```

Stable project defaults live in `config/deployment.defaults.json`. The generated `infra/deployment.auto.tfvars.json` and `infra/bootstrap/deployment.auto.tfvars.json` files are ignored by Git and must not be edited by hand. Infrastructure and demo scripts treat `.env` as authoritative, so stale shell exports cannot silently change deployment configuration. Image tags are generated after ECR repository creation and recorded in `.env` by the publishing script. Verify the local toolchain and selected AWS identity after rendering. Cloud resources are checked in later deployment phases:

```zsh
./scripts/infrastructure/check_prerequisites.sh local
```

Load the ignored local environment before running AWS CLI, Terraform or dashboard commands:

```zsh
set -a
source .env
set +a
```

Do not commit secrets, deployment identifiers, Terraform state, signed headers or generated workflow definitions.

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
./scripts/infrastructure/bootstrap.sh state-plan
```

Review and apply the bootstrap plan, run `./scripts/infrastructure/bootstrap.sh state-backup`, then run `./scripts/infrastructure/bootstrap.sh main-init`. For an existing environment, use the guarded `main-migrate` action documented in the lifecycle guide. Bootstrap inputs, backend configuration and state files are ignored by Git.

Start with the [first-deployment quickstart](docs/quickstart.md) for the shortest path from clone to live demo. The [bootstrap guide](docs/bootstrap.md) explains the deployment stages in more detail. The [infrastructure lifecycle guide](docs/infrastructure-lifecycle.md) covers persistent state, guarded teardown and recreation. The [external prerequisite inventory](docs/external-prerequisites.md) identifies account configuration outside the application stack. The [deployment guide](docs/deployment.md) covers GitHub OIDC and shared OpenLineage collector setup. Recovery, cost-control and operational checks are in the [operations runbook](docs/operations-runbook.md).

## Run the dashboards

After the target environment is deployed, launch the live cohort dashboard:

```zsh
./scripts/demo/start_live_dashboard.sh
```

Launch the separate model analytics dashboard in another terminal:

```zsh
./scripts/demo/start_model_analytics_dashboard.sh
```

The launch scripts load the selected AWS profile and region from `.env`. They retrieve realtime endpoints from Terraform outputs and analytical names from generated Terraform configuration. The live dashboard uses AWS IAM credentials to sign REST and WebSocket requests. The model dashboard queries Athena for probability-ranked approved-model scores, feature-window vital summaries, encounter context, freshness and governance labels.

## Demo and operations

Use the [demo guide](docs/demo-guide.md) for a complete live walkthrough, including startup, dashboard validation, Postman REST and WebSocket checks, CloudWatch review and shutdown.

Use the [load-testing guide](docs/load-testing.md) to run an isolated test that measures Kinesis-to-DynamoDB processing and WebSocket delivery latency without writing test events into the analytical lakehouse.

## Data governance

The [data governance guide](docs/data-governance.md) documents datasets, schema controls, quality gates, deduplication, retention, replay and evidence expectations.

The [analytics star schema](docs/analytics-star-schema.md) defines the observation fact grain, conformed dimensions, key strategy, active-cohort and encounter-boundary rules and bus matrix.

The [model-training guide](docs/model-training.md) defines the inference-safe training windows and reproducible logistic-regression baseline. The [model-predictions guide](docs/model-predictions.md) covers daily approved-model scoring and Athena presentation datasets. The [Power BI connection guide](docs/power-bi-connection.md) documents the completed Athena connection. The local `.pbix` remains outside the repository and is not a release artifact.

The [technology inventory](docs/technology-inventory.md) lists the standards, AWS services, frameworks, libraries, delivery tools and testing methods used by the project.

The [project build article](docs/building-healthcare-realtime-monitoring.md) provides a publication-ready narrative of the architecture, implementation, validation and operational lessons from start to finish.

## Portfolio safety

Public artifacts must use placeholders for account IDs, buckets, endpoints, load balancers, local usernames, secrets and signed headers. The project’s tracked examples are designed to be reproducible without revealing a deployed environment.
