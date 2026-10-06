# Healthcare Realtime Monitoring

[![continuous integration (CI)](https://github.com/ian-mungai/healthcare-realtime-monitoring/actions/workflows/ci.yml/badge.svg)](https://github.com/ian-mungai/healthcare-realtime-monitoring/actions/workflows/ci.yml)

An Amazon Web Services (AWS) portfolio project for synthetic realtime vital-sign monitoring. It ingests Beth Israel Deaconess Medical Center (BIDMC) waveform-derived measurements as Fast Healthcare Interoperability Resources (FHIR) observations, maintains current patient state for live clients and builds governed analytical datasets for quality validation and reporting.

This repository uses synthetic Synthea data and waveform-derived measurements for demonstration only. It is not a clinical decision-support system and must not be used for patient care.

## Table of Contents

- [Security](#security)
- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Terminology](#terminology)
- [Architecture](#architecture)
- [Data](#data)
- [Deploy and Teardown](#deploy-and-teardown)
- [Repository Layout](#repository-layout)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [License](#license)

## Security

Public artifacts must use placeholders for account IDs, buckets, endpoints, load balancers, local usernames, secrets and signed headers. The project’s tracked examples are designed to be reproducible without revealing a deployed environment.

Do not commit secrets, deployment identifiers, Terraform state, signed headers or generated workflow definitions. Every commit runs the quality checks: gitleaks, a whole-project scan for personal data and environment-specific values, blocks on credential and data files, lint and type checks and a commit-message check for Conventional Commit subjects and AI attribution. CI runs the same hooks and scans the full Git history for secrets.

## Background

The project demonstrates a realtime and analytical healthcare data platform built end to end on AWS. Releases v1.0.0 and v1.0.1 include the scope recorded in their release notes; the [v1.0.1 release notes](docs/release-notes-v1.0.1.md) summarize the current verified scope. The stack is torn down between demonstrations because it costs money while running.

### What It Demonstrates

- FHIR R4 observation ingestion through HAPI FHIR and a protected webhook.
- Kinesis-based realtime processing with latest-state delivery over Identity and Access Management (IAM)-authorized Representational State Transfer (REST) and WebSocket APIs.
- Separate Streamlit dashboards for live cohort monitoring and approved-model analytics.
- Durable normalized-event landing, Glue/Iceberg processing, Athena validation, dbt models, automated approved-model scoring, Soda contracts and OpenLineage events collected by IAM-protected Marquez or stored in S3.
- Bounded replay through encrypted Simple Queue Service (SQS) failure queues and a replay Lambda.
- Terraform-managed AWS infrastructure, CloudWatch dashboards, alarms and workload-scoped IAM roles.

## Install

### Prerequisites

- macOS or a compatible Unix shell
- Python 3.12
- Node.js 22 or later with npm for the isolated Markdown checker
- Terraform 1.11 or later
- AWS command-line interface (CLI) authenticated to the target account
- jq, used by the deployment, FHIR setup and dashboard scripts
- A temporary administrator or approved bootstrap identity for first deployment
- Docker, when building Elastic Container Service (ECS) images locally
- Java 17 and Gradle, when generating Synthea data
- Power BI Desktop and the Amazon Athena Open Database Connectivity (ODBC) driver, only when reproducing the completed reporting connection

### Local Setup

Clone the repository and create a local Python environment:

```zsh
cd healthcare-realtime-monitoring
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements_dev.txt
.venv/bin/python -m tools.install_tools   # pinned repository tools, including markdownlint-cli2, in .tools/
git config core.hooksPath .githooks          # pre-commit hooks and the commit-message check
```

Create the one ignored local configuration file:

```zsh
if [ ! -e "${PROJECT_ENV_FILE:-.env}" ]; then
  cp .env.example "${PROJECT_ENV_FILE:-.env}"
fi
```

Complete the placeholders in the selected `${PROJECT_ENV_FILE:-.env}` file, then render both Terraform inputs:

```zsh
./scripts/infrastructure/render_project_config.sh
```

Stable project defaults live in `config/deployment.defaults.json`. The generated `infra/deployment.auto.tfvars.json` and `infra/bootstrap/deployment.auto.tfvars.json` files are ignored by Git and must not be edited by hand. Infrastructure and demo scripts treat `.env` as authoritative, so stale shell exports cannot silently change deployment configuration. Image tags are generated after Elastic Container Registry (ECR) repository creation and recorded in the selected `${PROJECT_ENV_FILE:-.env}` file by the publishing script. Verify the local toolchain and selected AWS identity after rendering. Cloud resources are checked in later deployment phases:

```zsh
./scripts/infrastructure/check_prerequisites.sh local
```

Load the ignored local environment before running AWS CLI, Terraform or dashboard commands:

```zsh
set -a
source "${PROJECT_ENV_FILE:-.env}"
set +a
```

## Usage

### Validate the Repository

These commands mirror the local-CI checks in `.github/workflows/ci.yml`. Run `.venv/bin/pre-commit run --all-files` for the repository checks described in the quality checks guide:

```zsh
.venv/bin/python -m pytest tests scripts/synthea_loader/tests/test_load_fhir.py services/fhir_webhook/tests services/vitals_simulator/tests services/vitals_stream_processor/tests services/vitals_replay/tests services/vitals_api/tests services/websocket_handler/tests --cov -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m mypy .
for contract in data_quality/soda/contracts/*.yml; do .venv/bin/soda contract test --contract "$contract"; done
PYTHONPATH="$PWD/airflow/serverless:$PWD/airflow/dags:$PWD" .venv/bin/python -m unittest discover -s airflow/serverless/tests -v
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
```

The `--cov` run enforces the coverage minimum set in `pyproject.toml`. CI runs `scripts/synthea_loader/tests/test_synthea_output.py` separately, after generating the Synthea cohort, because it checks generated output.

### End-to-End Verification

End-to-End (E2E) runs need a deployed environment. `.venv/bin/python -m e2e.run session` runs the realtime, access, rejection and replay scenarios of the end-to-end test plan and writes a report for each under `artifacts/e2e/`. The [load-testing guide](docs/load-testing.md) runs the isolated Kinesis-to-DynamoDB-to-WebSocket test and saves a JavaScript Object Notation (JSON) and Markdown report for every run under `artifacts/e2e/load_test/`. The [demo guide](docs/demo-guide.md) and the [release checklist](docs/release-checklist.md) cover the full realtime and analytical path; verified results are recorded in the release notes.

### Run the Dashboards

After the target environment is deployed, launch the live cohort dashboard:

```zsh
./scripts/demo/start_live_dashboard.sh
```

Launch the separate model analytics dashboard in another terminal:

```zsh
./scripts/demo/start_model_analytics_dashboard.sh
```

The launch scripts load the selected AWS profile and region from the selected `${PROJECT_ENV_FILE:-.env}` file. They retrieve realtime endpoints from Terraform outputs and analytical names from generated Terraform configuration. The live dashboard uses AWS IAM credentials to sign REST and WebSocket requests. The model dashboard queries Athena for probability-ranked approved-model scores, feature-window vital summaries, encounter context, freshness and governance labels.

### Demo and Operations

Use the [demo guide](docs/demo-guide.md) for a complete live walkthrough, including startup, dashboard validation, Postman REST and WebSocket checks, CloudWatch review and shutdown.

Use the [load-testing guide](docs/load-testing.md) to run an isolated test that measures Kinesis-to-DynamoDB processing and WebSocket delivery latency without writing test events into the analytical lakehouse.

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **BI**: business intelligence.
- **BIDMC**: Beth Israel Deaconess Medical Center.
- **CI**: continuous integration.
- **CLI**: command-line interface.
- **E2E**: end-to-end.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **IAM**: Identity and Access Management.
- **IP**: Internet Protocol.
- **JSON**: JavaScript Object Notation.
- **MWAA**: Managed Workflows for Apache Airflow.
- **NEWS2**: National Early Warning Score 2.
- **NPPES**: National Plan and Provider Enumeration System.
- **ODBC**: Open Database Connectivity.
- **OIDC**: OpenID Connect.
- **REST**: Representational State Transfer.
- **SQL**: Structured Query Language.
- **SQS**: Simple Queue Service.
- **VPC**: virtual private cloud.

## Architecture

![Healthcare Realtime Monitoring architecture](docs/architecture/architecture.png)

The diagram source is [docs/architecture/architecture.html](docs/architecture/architecture.html). The [architecture guide](docs/architecture.md) describes the realtime path, analytical path, recovery model, security boundaries and observability design.

The diagram is a design snapshot identified as commit `8f7c07c`. Its synthetic-only footer does not describe the public deidentified BIDMC measurements. [Data](#data) records the source provenance; the architecture guide explains the diagram's historical boundary.

```text
Simulator -> HAPI FHIR -> webhook -> Kinesis -> Lambda -> DynamoDB -> REST/WebSocket -> live cohort dashboard
                                            \-> Firehose -> S3 -> Glue -> Athena -> dbt -> ML scoring -> model analytics dashboard
                                                                                         \-> Soda
```

## Data

| Source | Use | Classification | Terms of use |
| --- | --- | --- | --- |
| [Synthea](https://github.com/synthetichealth/synthea) v4.0.0 | Synthetic patients, encounters and blood-pressure readings loaded into HAPI FHIR or exported for the simulator | Synthetic | Synthea software is Apache License 2.0 |
| [BIDMC PPG and Respiration Dataset](https://physionet.org/content/bidmc/1.0.0/) (PhysioNet) | De-identified waveform-derived heart rate, respiratory rate and SpO₂ readings replayed by the simulator | Public | Open Data Commons Attribution License v1.0; cite Pimentel et al., IEEE Transactions on Biomedical Engineering 64(8), 2016 and PhysioNet |
| Committed provider seed (`dbt/seeds/provider_history.csv`) | National Plan and Provider Enumeration System (NPPES)-compatible provider history for the type 2 provider dimension | Synthetic | Fictional clinicians created for this repository |

The simulator attaches public de-identified BIDMC heart-rate, respiratory-rate and oxygen-saturation readings and synthetic Synthea blood pressure to synthetic Synthea patient identities. Outcome scenarios can transform these readings to produce the synthetic deterioration proxy. The analytical models label their rows `data_classification = 'synthetic'`; that label does not change the public recordings' provenance.

The [data governance guide](docs/data-governance.md) documents datasets, schema controls, quality gates, deduplication, retention, replay and evidence expectations.

The [analytics star schema](docs/analytics-star-schema.md) defines the observation fact grain, conformed dimensions, key strategy, active-cohort and encounter-boundary rules and bus matrix.

The [model-training guide](docs/model-training.md) defines the inference-safe training windows and reproducible logistic-regression baseline. The [model-predictions guide](docs/model-predictions.md) covers daily approved-model scoring and Athena presentation datasets. The [Power BI connection guide](docs/power-bi-connection.md) documents the completed Athena connection. The local `.pbix` remains outside the repository and is not a release artifact.

The [technology inventory](docs/technology-inventory.md) lists the standards, AWS services, frameworks, libraries, delivery tools and testing methods used by the project.

The [v1.0.1 release notes](docs/release-notes-v1.0.1.md) summarize the current verified release scope, acceptance evidence and documented limitations. The [v1.0.0 release notes](docs/release-notes-v1.0.0.md) remain available as the initial release record.

## Deploy and Teardown

Start with the [first-deployment quickstart](docs/quickstart.md). It is the only complete command sequence for a fresh clone, account or region. Development and production run in separate AWS accounts; the [environments guide](docs/environments.md) explains how to select one. Terraform uses a protected S3 backend with native state locking and generated ignored inputs derived from the selected `${PROJECT_ENV_FILE:-.env}` file.

Cohort loading and subscription registration run as a one-off ECS task inside the virtual private cloud (VPC), so no personal Internet Protocol (IP) address is opened to HAPI ([FHIR setup tasks](docs/fhir-setup-tasks.md)). The [deployment stages and recovery guide](docs/bootstrap.md) explains interrupted stages. The [infrastructure lifecycle guide](docs/infrastructure-lifecycle.md) covers state migration, guarded teardown, account retirement and recreation. The [external prerequisite inventory](docs/external-prerequisites.md) identifies account configuration outside the application stack. The [deployment guide](docs/deployment.md) covers GitHub OpenID Connect (OIDC) and the optional shared OpenLineage collector. Recovery, cost control and operational checks are in the [operations runbook](docs/operations-runbook.md).

Tear the stack down after every demo with the [controlled application teardown](docs/infrastructure-lifecycle.md#controlled-application-teardown). Review and apply protection removal, preview and approve storage cleanup, then review and apply destruction. Each apply requires approval and the environment-specific `CONFIRM_TEARDOWN`; verify empty application state and retained prerequisites.

## Repository Layout

| Path | Contents |
| --- | --- |
| `infra/` | Terraform root and AWS service modules |
| `services/` | Webhook, realtime processor, application programming interface (API), replay, WebSocket and simulator services |
| `dashboard/` | Streamlit live cohort and model analytics clients |
| `jobs/` | Glue, dbt, machine-learning and FHIR setup runtime jobs |
| `airflow/` | Managed Workflows for Apache Airflow (MWAA) Serverless workflow source and generator |
| `dbt/` | dbt silver (staging) and gold (dimensional and analytical) models, seeds and tests |
| `data_quality/` | Great Expectations and Soda validation assets |
| `lineage/` | OpenLineage event emitters |
| `scripts/` | Build, test-data, load-test and demo helpers |
| `deploy/` | Container definitions for dbt, Soda and Marquez |
| `config/` | Shared vital-sign catalog and deployment defaults |
| `tests/` | Contract, infrastructure, lineage, dashboard and pipeline tests |
| `testkit/` | Shared test expectations used instead of `assert` |
| `tools/` | Repository checks, pinned tool installer, Structured Query Language (SQL) lint runner and documentation-review tooling |
| `e2e/` | End-to-End scenarios run against a deployed stack |
| `docs/` | Architecture, governance, operations, demo and Power BI connection documentation |

## Limitations

- Patient identities and encounters are synthetic. Heart rate, respiratory rate and oxygen saturation use public de-identified physiological recordings; blood pressure comes from Synthea. Replaying real physiological measurements under synthetic identities does not make their source synthetic.
- The deterioration label is a synthetic engineering proxy derived from National Early Warning Score 2 (NEWS2) extreme thresholds. The model is not clinically validated and must not be used for patient care.
- The portfolio environment keeps short log and backup retention to control cost. A production deployment would need formal retention, recovery, compliance and clinical-safety review.
- There is no live public demo, because the full AWS stack is billable while it runs.

## Contributing

Individual project; contributions are not accepted.

## License

[MIT](LICENSE) © 2026 Ian Mungai. Third-party data keeps its own terms; see [Data](#data).
