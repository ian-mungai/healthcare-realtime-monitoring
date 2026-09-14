# Technology Inventory

This inventory lists technologies used by committed code, infrastructure, tests, or documented operator workflows. The project uses synthetic data and is not a clinical system.

## Healthcare and data standards

| Technology | Project use |
| --- | --- |
| FHIR R4 and HAPI FHIR | Patient, Encounter, Observation, and Subscription exchange through the self-hosted FHIR service |
| LOINC | Canonical vital-sign codes controlled by `config/vital_signs.json` |
| Synthea | Deterministic synthetic patient and encounter generation |
| PhysioNet BIDMC and WFDB | Waveform-derived demonstration vital signs with retry and S3 caching |
| NEWS2-informed thresholds | Transparent synthetic deterioration proxy and dashboard context, not clinical validation |

## AWS platform

| Area | Services and use |
| --- | --- |
| Network and compute | VPC, public/private subnets, internet/NAT gateways, security groups, Application Load Balancer, ECS on Fargate, ECR, Lambda |
| Streaming and storage | Kinesis Data Streams, Kinesis Data Firehose, versioned encrypted S3, DynamoDB, SQS and dead-letter queues |
| APIs and databases | API Gateway HTTP/WebSocket APIs, VPC Link, HAPI FHIR, RDS for PostgreSQL |
| Analytics | AWS Glue Data Catalog and PySpark jobs, Apache Iceberg, Athena, MWAA Serverless |
| Security and operations | IAM, GitHub OIDC federation, Secrets Manager, KMS, SNS, CloudWatch logs, metrics, dashboards, alarms, and PITR |

## Analytics, quality, and ML

| Technology | Project use |
| --- | --- |
| Apache Airflow 3 | Portable native DAG and source contract for the generated serverless workflow |
| MWAA Serverless | Daily AWS-managed orchestration without a continuously running Airflow environment |
| dbt Core and dbt-athena | Staging, Kimball dimensions/fact, fixed-window features, model inputs, and prediction views |
| Great Expectations and Soda | Processed-table expectations plus analytical contracts and prediction freshness |
| OpenLineage and Marquez | START/COMPLETE/FAIL lineage events, shared collector, SigV4 transport, and S3 fallback |
| pandas, PyAthena, scikit-learn, joblib | Athena feature loading, logistic regression, evaluation, serialization, and approved-model scoring |
| Kimball modeling and SCD Type 2 | Conformed dimensions, observation fact grain, surrogate keys, and provider-history preservation |
| JSON, NDJSON, Parquet, and YAML | API/event contracts, partitioned model predictions, analytical storage, and declarative configuration |

## Application, delivery, and testing

| Area | Tools and methods |
| --- | --- |
| Monitoring client | Streamlit, Altair, REST polling, WebSocket updates, AWS SigV4 |
| HTTP and service integration | Requests, HTTPX, Respx, WebSocket Client, Botocore signing, SQLAlchemy, and PostgreSQL drivers |
| Manual verification | Postman, AWS CLI, GitHub CLI, `jq`, Athena SQL, CloudWatch dashboards |
| Infrastructure and delivery | Terraform AWS/AWSCC providers, Docker Buildx, Git, GitHub Actions, OIDC, protected environments, immutable image tags |
| Quality engineering | pytest, unittest, pytest-cov, Ruff, MyPy, Terraform tests, container smoke tests, and contract syntax checks |
| Test-data toolchain | Java 17, Gradle, Synthea, WFDB, deterministic seeds, and patient/encounter mapping |
| Optional reporting | Power BI Desktop through the Amazon Athena connector and Athena ODBC 2.x driver |

Versions are pinned in Terraform constraints, Python requirements, Docker build arguments, GitHub workflows, and the Synthea version file. Review those machine-readable files rather than copying version numbers from prose.
