# Building an End-to-End Healthcare Realtime Monitoring Platform on AWS

Healthcare data engineering is difficult for reasons that have little to do with drawing a chart. A useful monitoring platform must accept clinical data safely, preserve meaning across several processing layers, surface changes quickly, support historical analysis and explain where every result came from.

This project was built as a synthetic portfolio system to explore that full path. It is not a medical device and does not use real patient data. Its purpose is to demonstrate the engineering methods behind a reproducible realtime and analytical platform.

The final system combines FHIR, streaming services, serverless processing, a lakehouse, workflow orchestration, data quality, lineage, machine learning, operational dashboards and business intelligence. More importantly, it treats those pieces as one system rather than a collection of disconnected demos.

## Starting with a reproducible synthetic cohort

The project begins with Synthea-generated FHIR resources. Synthea provides realistic but fictional patients, encounters, organizations and observations, which makes it suitable for public engineering work without exposing protected health information.

A loader publishes the generated resources to a HAPI FHIR server and writes a patient-to-encounter mapping for the simulator. The active demonstration cohort is deliberately small: ten patients. Keeping the cohort bounded makes realtime behavior easy to inspect while still exercising multi-patient monitoring, encounter relationships and analytical joins.

The simulator uses BIDMC waveform-derived vital-sign patterns to publish heart rate, respiratory rate, oxygen saturation and blood pressure observations. Retry and backoff logic protects external data retrieval, while an encrypted object-store cache makes repeated runs durable and less dependent on an upstream source. Event timestamps are assigned when observations are published so the dashboard reflects current event time instead of replay-file time.

## Moving FHIR events through the realtime path

Each generated Observation is written to HAPI FHIR. A FHIR subscription sends the event to a protected webhook, which validates the shared secret and the expected vital-sign profile before accepting the payload.

The webhook transforms the FHIR resource into a compact versioned event and writes it to Amazon Kinesis Data Streams. The event retains the source observation, patient, encounter, vital type, LOINC code, value, unit and timestamps. Preserving `encounter_id` at this boundary proved especially important: an identifier lost during ingestion cannot be reconstructed reliably later in the pipeline.

An AWS Lambda processor consumes the stream and maintains two DynamoDB views. One stores processed observations, while the other stores the latest merged vital snapshot for each patient. The processor combines separately arriving heart rate, respiratory rate, oxygen saturation and blood pressure observations without erasing fields that were not present in the newest partial event.

The same Lambda publishes updates through an API Gateway WebSocket API. A REST API provides the latest snapshot as a fallback, allowing the Streamlit dashboard to recover when a socket disconnects or a browser misses an update.

## Designing the dashboard around a nursing workflow

The first dashboard versions focused too heavily on one patient. That design made the system look realtime, but it did not answer the operational question: which patient needs attention now?

The dashboard was redesigned around the ten-patient cohort. Every patient remains visible, current/stale state is explicit and focused trend views do not remove the rest of the cohort from view. Clinical ranges are presented as monitoring context, with clear synthetic and nonclinical labeling. Trend charts use full timestamps and separate vital scales so unlike units are never plotted as if they were directly comparable.

Freshness is treated as a functional requirement. With a five-second simulator cadence, data older than ten seconds is stale. WebSocket updates provide the fastest path, while REST polling prevents the interface from freezing silently. CloudWatch dashboards and alarms provide the infrastructure view behind the clinical-style interface, including stream delay, Lambda errors and throttles, WebSocket failures, simulator publishing failures and processing latency.

## Building a lakehouse from the same event stream

Kinesis also feeds Amazon Data Firehose, which stores the raw event history in Amazon S3. An AWS Glue job reads that history, resolves schema choices, quarantines malformed records and writes processed observations as Apache Iceberg data registered in the Glue Data Catalog.

Athena provides the query layer. dbt then transforms the processed observations into a star schema with patient, encounter, provider, observation-type and date dimensions plus an observation fact table.

The analytical boundary intentionally differs from the immutable source boundary. Raw and processed storage retain historical events for audit and replay, including older records that predate encounter propagation. The dbt staging model includes only the configured ten-patient cohort and observations with a valid encounter identifier. This prevents blank encounter keys and stale test patients from leaking into the portfolio-facing star schema without rewriting source history.

The encounter feature model follows the repository's fact-table naming convention. It aggregates a fixed initial feature window and a following outcome window for each encounter. The model supports both analytical exploration and a versioned synthetic deterioration proxy.

## Making quality and lineage part of execution

Data quality is not a single test at the end of the pipeline. The project uses several complementary layers:

- FHIR profile validation checks the clinical resource contract at ingestion.
- dbt tests protect keys, relationships, accepted values and model grain.
- Great Expectations validates processed analytical data.
- Soda contracts validate the published analytical tables.
- Quarantine and replay paths retain failed events for controlled recovery.

OpenLineage events connect the major processing stages. Glue, Athena validation, dbt, Great Expectations, Soda and model operations emit START and COMPLETE events to a shared Marquez collector. This provides a cross-tool view of what ran, which datasets were read or written and whether execution completed.

Amazon Managed Workflows for Apache Airflow Serverless orchestrates the cloud workflow. The repository also includes a native Airflow DAG so the orchestration logic is portable beyond the managed service. The workflow runs Glue processing, analytical validation, dbt models, quality checks, model scoring, prediction refresh and lineage emission in dependency order.

## Adding machine learning without overstating it

The machine-learning component is deliberately modest. It trains a logistic-regression baseline on encounter-level vital features and a synthetic deterioration proxy label. Patients are grouped into deterministic train and test partitions to prevent the same patient from appearing on both sides of evaluation.

Training records the feature definition, label definition, dataset fingerprint, metrics, threshold and model version. Scoring resolves an explicitly approved model version rather than a mutable `latest` reference. Published predictions are labeled as synthetic portfolio output and not clinically validated.

The pipeline also knows when not to train. If the eligible cohort contains only one label class, scheduled training remains paused because accuracy from that dataset would not be meaningful. This is an important production habit: automation should enforce analytical prerequisites, not merely execute code on schedule.

## Treating operations and security as product features

Infrastructure is defined with Terraform and separated into modules for networking, storage, streaming, compute, APIs, monitoring, orchestration and lineage. Container images use immutable tags in Amazon ECR, while Lambda and workflow packages are built reproducibly.

Private deployment values stay outside tracked files. Environment files supply local operational settings, ignored Terraform inputs hold private infrastructure values and GitHub Actions retrieves larger encrypted deployment configuration from AWS after authenticating through OpenID Connect. Public documentation uses variable names and placeholders rather than account IDs, bucket names, endpoints or local paths.

The repository includes controlled bootstrap and teardown workflows. Terraform state lives in a persistent versioned location outside the disposable project resources. Cleanup tooling handles versioned object storage and container registries, while deletion protection is variable driven. This allows the deployed environment to be removed and recreated without pretending that externally managed prerequisites do not exist.

Operational failure paths are equally deliberate. SQS dead-letter queues retain failed realtime events, replay tooling supports controlled recovery, alarms cover queue depth and processing failures and runbooks document startup, shutdown, replay and verification. Cost controls keep scheduled workloads and demonstration services from running unnecessarily.

## Presenting the analytical result in Power BI

Power BI was connected to Athena through the Amazon Athena ODBC driver. The completed local report uses DirectQuery so its visuals query the analytical layer without importing the full dataset into the file.

The report design includes four pages:

1. A cohort overview with patient, encounter, observation and freshness measures.
2. Vital trends with patient and encounter filters plus separate small multiples for each vital type.
3. Encounter analysis with drillthrough, provider context and feature-window summaries.
4. Model analytics with probability, proxy risk band, model version and prominent nonclinical labeling.

The local Streamlit experience keeps operational monitoring and analytical model review separate. The live dashboard follows current vital-sign changes across the ten-patient cohort. The model analytics dashboard queries Athena for the latest approved score per patient and adds encounter context, feature-window vital summaries, the decision threshold, model and schema versions, freshness, prediction scope and clinical-validation status.

The `.pbix` remains outside the repository because it is a binary file that can retain connection metadata and cached previews. Publishing to Power BI Service is optional and restricted to a private workspace. The project does not use Publish to web.

## Technology and methods used

| Discipline | Tools and methods |
| --- | --- |
| Data engineering | Python, Boto3, HTTPX, FHIR R4, HAPI FHIR, Synthea with Java and Gradle, PhysioNet BIDMC, WFDB, Kinesis Data Streams, Data Firehose, Lambda, DynamoDB, S3, Glue with PySpark, Apache Iceberg, Athena, dbt, Airflow, MWAA Serverless, ECS Fargate and Docker |
| Data analytics | SQL, Athena validation queries, Kimball dimensional modeling, SCD Type 2 provider history, cohort filtering, observation grain tests, fixed encounter windows and Power BI DirectQuery reporting |
| Data science | pandas, NumPy, PyAthena, scikit-learn logistic regression, deterministic patient-level splits, classification metrics, joblib model serialization, versioned model approval and synthetic proxy scoring |
| Quality and governance | FHIR profile validation, dbt tests, Great Expectations, Soda contracts, quarantine and replay, OpenLineage, Marquez, dataset fingerprints and synthetic-data labeling |
| Platform and delivery | Terraform, AWS and AWSCC providers, IAM, SigV4, Secrets Manager, KMS, CloudWatch, SQS dead-letter queues, Amazon ECR, Git, GitHub Actions, GitHub OIDC, pytest, Ruff, MyPy, container smoke tests and Postman |
| Application and visualization | Streamlit, Altair, REST polling, WebSockets, API Gateway, Power BI, DAX, drillthrough, synchronized slicers and nursing-oriented freshness indicators |

The repository contains the application code, infrastructure, tests, runbooks and architecture documentation needed to deploy and examine the system. The dataset and deterioration label remain synthetic and the project is not intended for patient care.
