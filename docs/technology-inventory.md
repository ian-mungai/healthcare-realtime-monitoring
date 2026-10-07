---
title: "Technology Inventory"
description: "Locate implemented components, runtime tools and their repository sources."
last_updated: 2026-10-07
audience: [developer, operator]
---

# Technology Inventory

For developers and operators: locate implemented components, runtime tools and their repository sources. This inventory lists technologies used by committed code, infrastructure, tests or documented operator workflows. The project uses synthetic identities and demonstration measurements and is not a clinical system.

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **BI**: business intelligence.
- **BIDMC**: Beth Israel Deaconess Medical Center.
- **CLI**: command-line interface.
- **DAG**: directed acyclic graph.
- **DAX**: Data Analysis Expressions.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **HTTP**: HyperText Transfer Protocol.
- **IAM**: Identity and Access Management.
- **JSON**: JavaScript Object Notation.
- **KMS**: Key Management Service.
- **LOINC**: Logical Observation Identifiers Names and Codes.
- **ML**: machine learning.
- **MWAA**: Managed Workflows for Apache Airflow.
- **NAT**: network address translation.
- **NDJSON**: newline-delimited JSON.
- **NEWS2**: National Early Warning Score 2.
- **ODBC**: Open Database Connectivity.
- **OIDC**: OpenID Connect.
- **PITR**: point-in-time recovery.
- **RDS**: Relational Database Service.
- **REST**: Representational State Transfer.
- **SCD**: slowly changing dimension.
- **SNS**: Simple Notification Service.
- **SQL**: Structured Query Language.
- **SQS**: Simple Queue Service.
- **VPC**: virtual private cloud.
- **WFDB**: Waveform Database.
- **YAML**: YAML Ain't Markup Language.

## Healthcare and Data Standards

| Technology | Project use |
| --- | --- |
| Fast Healthcare Interoperability Resources (FHIR) R4 and HAPI FHIR | Patient, Encounter, Observation and Subscription exchange through the self-hosted FHIR service |
| Logical Observation Identifiers Names and Codes (LOINC) | Canonical vital-sign codes controlled by `config/vital_signs.json` |
| Synthea | Deterministic synthetic patient and encounter generation |
| PhysioNet Beth Israel Deaconess Medical Center (BIDMC) and Waveform Database (WFDB) | Waveform-derived demonstration vital signs with retry and S3 caching |
| National Early Warning Score 2 (NEWS2)-informed thresholds | Transparent synthetic deterioration proxy and dashboard context, not clinical validation |

## AWS Platform

| Area | Services and use |
| --- | --- |
| Network and compute | virtual private cloud (VPC), public/private subnets, internet/network address translation (NAT) gateways, security groups, Application Load Balancer, Elastic Container Service (ECS) on Fargate, Elastic Container Registry (ECR), Lambda |
| Streaming and storage | Kinesis Data Streams, Kinesis Data Firehose, versioned encrypted S3, DynamoDB, Simple Queue Service (SQS) and dead-letter queues |
| APIs and databases | application programming interface (API) Gateway HyperText Transfer Protocol (HTTP)/WebSocket APIs, VPC Link, HAPI FHIR, Relational Database Service (RDS) for PostgreSQL |
| Analytics | Amazon Web Services (AWS) Glue Data Catalog and PySpark jobs, Apache Iceberg, Athena, Managed Workflows for Apache Airflow (MWAA) Serverless |
| Security and operations | Identity and Access Management (IAM), GitHub OpenID Connect (OIDC) federation, Secrets Manager, Key Management Service (KMS), Simple Notification Service (SNS), CloudWatch logs, metrics, dashboards, alarms and point-in-time recovery (PITR) |

## Analytics, Quality and ML

| Technology | Project use |
| --- | --- |
| Apache Airflow 3.3.1 and SQLAlchemy 2.0.50 | Portable native directed acyclic graph (DAG), workflow-generation contract and Structured Query Language (SQL) persistence compatibility in the pinned local toolchain |
| MWAA Serverless | Daily AWS-managed orchestration without a continuously running Airflow environment |
| dbt Core and dbt-athena | Silver staging model, gold Kimball dimensions/fact, fixed-window features, model inputs and prediction views |
| dbt-postgres 1.11.0 | The same dbt models on the local Postgres warehouse, through cross-adapter macros (Local Stack) |
| Great Expectations and Soda | Processed-table expectations plus analytical contracts and prediction freshness |
| OpenLineage and Marquez | START/COMPLETE/FAIL lineage events, shared collector, SigV4 transport and S3 fallback |
| Python, SQL, pandas, NumPy, PyAthena, scikit-learn, statsmodels, JupyterLab and joblib | Data preparation, Athena analysis, feature engineering, logistic regression, evaluation, serialization and approved-model scoring |
| Kimball modeling and slowly changing dimension (SCD) Type 2 | Conformed dimensions, observation fact grain, surrogate keys and provider-history preservation |
| JavaScript Object Notation (JSON), newline-delimited JSON (NDJSON), Parquet and YAML Ain't Markup Language (YAML) | API/event contracts, partitioned model predictions, analytical storage and declarative configuration |
| Analytical methods | Cohort filtering, data profiling, dimensional modeling, deterministic patient splits, fixed feature/outcome windows, classification metrics and synthetic proxy labeling |

## Application, Delivery and Testing

| Area | Tools and methods |
| --- | --- |
| Monitoring and analytics clients | Streamlit live cohort and model analytics dashboards, Altair, Athena queries, Representational State Transfer (REST) polling, WebSocket updates, AWS SigV4 |
| HTTP and service integration | Requests, HTTPX, Respx, WebSocket Client, Botocore signing, SQLAlchemy and PostgreSQL drivers |
| Manual verification | Postman, AWS command-line interface (CLI), GitHub CLI, `jq`, Athena SQL, CloudWatch dashboards |
| Infrastructure and delivery | Terraform AWS/AWSCC providers, Docker Buildx, Git, GitHub Actions, OIDC, protected environments, immutable image tags |
| Local development | Docker Compose stack with PostgreSQL 16, HAPI FHIR and Grafana on localhost-only ports, checked by `e2e.local_stack`; the local warehouse is checked by `e2e.local_warehouse` (Local Stack) |
| Quality engineering | pytest, unittest, pytest-cov, Ruff, MyPy, Terraform tests, container smoke tests, contract syntax checks, pre-commit, gitleaks, tflint, checkov, SQLFluff, vulture, deptry, dbt-project-evaluator, an Airflow DagBag test, a whole-project privacy scan and the `e2e` scenario runner |
| Test-data toolchain | Java 17, Gradle, Synthea, WFDB, deterministic seeds and patient/encounter mapping |
| Reporting | Power BI Desktop through the Amazon Athena connector and Athena Open Database Connectivity (ODBC) 2.x driver; the private guide documents DirectQuery pages, Data Analysis Expressions (DAX) measures, drillthrough and synchronized slicers. Native measure execution and finished-report behavior are unverified; the `.pbix` remains outside the repository |

Versions are pinned in Terraform constraints, Python requirements, Docker build arguments, GitHub workflows and the Synthea version file. The root development requirements include the Airflow generator requirements so a fresh clone resolves one tested environment. Review those machine-readable files rather than copying version numbers from prose.
