---
title: "Architecture"
description: "Trace realtime delivery, analytical processing, recovery and security boundaries."
last_updated: 2026-10-07
audience: [developer, operator]
---

# Architecture

For developers and operators: trace realtime delivery, analytical processing, recovery and security boundaries.

## Contents

- [Terminology](#terminology)
- [Purpose](#purpose)
- [System Overview](#system-overview)
- [Realtime Path](#realtime-path)
- [Analytical Path](#analytical-path)
- [Failure and Recovery Model](#failure-and-recovery-model)
- [Security Boundaries](#security-boundaries)
- [Observability](#observability)
- [Deployment and Configuration](#deployment-and-configuration)
- [Trade-Offs](#trade-offs)

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **BIDMC**: Beth Israel Deaconess Medical Center.
- **DAG**: directed acyclic graph.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **HTML**: HyperText Markup Language.
- **HTTP**: HyperText Transfer Protocol.
- **IAM**: Identity and Access Management.
- **MWAA**: Managed Workflows for Apache Airflow.
- **NAT**: network address translation.
- **PNG**: Portable Network Graphics.
- **RDS**: Relational Database Service.
- **REST**: Representational State Transfer.
- **SQS**: Simple Queue Service.
- **VPC**: virtual private cloud.

## Purpose

This portfolio project demonstrates an Amazon Web Services (AWS)-based healthcare monitoring platform using synthetic Synthea records and Beth Israel Deaconess Medical Center (BIDMC) waveform-derived vital signs. It is a technical demonstration, not a clinical system and not a source of patient-care decisions.

The design keeps three concerns distinct:

- low-latency patient-state delivery for monitoring clients;
- durable, governed analytical processing; and
- bounded failure recovery with observable operational controls.

## System Overview

The rendered diagram at [architecture/architecture.png](architecture/architecture.png) is built from [architecture/architecture.html](architecture/architecture.html).

Its synthetic-only footer does not describe the public BIDMC measurements' provenance. Patient identities and Synthea blood pressure are synthetic; heart rate, respiratory rate and oxygen saturation use public deidentified recordings. [Data](../README.md#data) records that source boundary. The Mermaid view and path descriptions below describe the implemented flows.

Rendering prerequisites:

- Google Chrome installed at the macOS path below.
- The repository root as the working directory.
- A reviewed change to the HyperText Markup Language (HTML) source.

1. Render the Portable Network Graphics (PNG) with headless Chrome:

   ```zsh
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars --window-size=1200,1180 --virtual-time-budget=5000 --screenshot=docs/architecture/architecture.png "file://$PWD/docs/architecture/architecture.html"
   ```

2. Open the generated PNG and verify that every label is readable, no content is clipped and the diagram matches the reviewed source.

The Mermaid view below shows the same data flow in text form.

```mermaid
flowchart LR
    subgraph Ingestion[Clinical event ingestion]
        SIM["BIDMC-backed vital-sign simulator"]
        HAPI["HAPI FHIR\nObservation API"]
        WEBHOOK["FHIR webhook Lambda"]
    end

    subgraph Realtime[Realtime serving path]
        KINESIS["Kinesis Data Stream"]
        PROCESSOR["Vitals processor Lambda"]
        LATEST["DynamoDB\nlatest patient state"]
        REST["IAM-authorized REST API"]
        WS["IAM-authorized WebSocket API"]
        CLIENT["Streamlit live cohort dashboard\nand Postman clients"]
    end

    subgraph Analytics[Durable analytical path]
        FIREHOSE["Kinesis Data Firehose"]
        RAW["Versioned S3\nnormalized FHIR vital events"]
        GLUE["Glue + Iceberg\nprocessed observations"]
        ATHENA["Athena quality validation"]
        GX["Great Expectations\nprocessed-table validation"]
        REF["FHIR setup task\ncohort reference extract"]
        DBT["dbt ECS task\nsilver and gold models"]
        ML["Approved logistic model\nautomated scoring"]
        PREDICT["Athena prediction\nserving views"]
        MODELCLIENT["Streamlit model\nanalytics dashboard"]
        SODA["Soda ECS task\ndata contracts"]
        POWERBI["Power BI\nAthena connection"]
    end

    subgraph Operations[Recovery and operations]
        FAILURES["Encrypted SQS\nfailure queue"]
        REPLAY["Replay Lambda"]
        DLQ["Replay dead-letter queue"]
        CW["CloudWatch dashboards\nand alarms"]
        LINEAGE["IAM-authorized Marquez collector\nor durable S3 fallback"]
    end

    SIM --> HAPI --> WEBHOOK --> KINESIS
    KINESIS --> PROCESSOR --> LATEST
    LATEST --> REST --> CLIENT
    PROCESSOR --> WS --> CLIENT

    KINESIS --> FIREHOSE --> RAW --> GLUE --> ATHENA --> GX --> REF --> DBT --> ML --> PREDICT --> SODA
    HAPI --> REF
    PREDICT --> MODELCLIENT
    PREDICT --> POWERBI
    GLUE --> LINEAGE
    ATHENA --> LINEAGE
    GX --> LINEAGE
    DBT --> LINEAGE
    SODA --> LINEAGE

    PROCESSOR -- failed records --> FAILURES --> REPLAY --> KINESIS
    FAILURES -- max receives --> DLQ
    REPLAY -- terminal records --> DLQ
    KINESIS --> CW
    PROCESSOR --> CW
    WEBHOOK --> CW
    HAPI --> CW
```

## Realtime Path

1. The simulator converts synthetic cohort measurements into Fast Healthcare Interoperability Resources (FHIR) R4 `Observation` resources and submits them to HAPI FHIR.
2. The HAPI subscription invokes the webhook Lambda. The webhook validates its shared secret and publishes normalized events to Kinesis.
3. The processor Lambda validates realtime payloads, rejects stale or duplicate state updates, writes the newest state per patient to DynamoDB and broadcasts accepted updates to connected WebSocket clients.
4. The Representational State Transfer (REST) application programming interface (API) provides an Identity and Access Management (IAM)-authorized latest-state fallback. The Streamlit dashboard uses the WebSocket feed while merging REST-polling results to remain responsive during a transient connection interruption.

The realtime serving model is deliberately cohort-first: the live dashboard keeps all simulated patients visible and permits an operator to focus on one patient without losing the wider clinical context.

## Analytical Path

Kinesis Data Firehose writes immutable normalized vital events to the data bucket. These rows preserve FHIR identifiers and coding but are not complete FHIR resources. Glue reads that current event contract, classifies each measurement, exposes rejected rows through an Athena-readable quarantine table and deduplicates and merges accepted measurements into an Iceberg table. Reviewed quarantine rows can be corrected and republished through the controlled replay utility. The native Airflow directed acyclic graph (DAG) and Managed Workflows for Apache Airflow (MWAA) Serverless workflow coordinate Glue, Athena validation, Great Expectations, the cohort reference extract, dbt, approved-model scoring, prediction refresh and Soda in sequence:

```text
raw event arrival -> Glue -> Athena -> Great Expectations -> cohort reference extract -> dbt -> approved-model scoring -> prediction refresh -> Soda
```

dbt produces a keyed observation fact, conformed dimensions, fixed-window encounter features and separate training and prospective-scoring datasets. The daily workflow scores the latter with one explicitly approved immutable model, publishes predictions to the Terraform-owned catalog named by `ATHENA_ML_DATABASE`, rebuilds the serving views and then runs freshness-aware Soda contracts. The separate model analytics dashboard joins the latest approved score to patient, encounter and feature-window context. It displays ranked proxy probability, model controls, scoring freshness and explicit synthetic and nonclinical labels without affecting live monitoring priorities. The [analytics star schema](analytics-star-schema.md) defines the analytical grain, keys, join paths and bus matrix. Each executed analytical validation emits OpenLineage lifecycle events with a shared run identity. The managed collector runs Marquez on private Elastic Container Service (ECS) and Relational Database Service (RDS) resources behind explicit IAM-authorized API Gateway routes. Emitters sign remote requests using temporary workload credentials; S3 remains the durable fallback when the collector is disabled.

## Failure and Recovery Model

The processor rejects records that fail validation without retrying them and counts them in the `PermanentRecordsRejected` metric. Retryable failures are retried by Lambda and then reported to an encrypted Simple Queue Service (SQS) failure queue. The replay Lambda retrieves the original range from the main vitals stream and republishes it once. A record already at the replay limit goes straight to a separate replay dead-letter queue with its reason; a failure message that cannot be replayed, including any from the isolated load-test stream, moves there after five failed receives. Operators investigate the dead-letter queue; see [data governance](data-governance.md#failure-handling-and-replay).

This design prefers controlled replay over blind redrive: an operator should identify the underlying data or deployment issue, inspect the dead-letter record and then validate fresh state, dashboard behavior and alarms after recovery. The full procedure is in [operations-runbook.md](operations-runbook.md).

## Security Boundaries

- HAPI FHIR runs behind an application load balancer that accepts HyperText Transfer Protocol (HTTP) only from the network address translation (NAT) gateway, as configured in [the Terraform root](../infra/main.tf). The simulator and one-off [FHIR setup task](fhir-setup-tasks.md) use that path without operator-machine access; the service and database remain in the project virtual private cloud (VPC). The [security reference](data-governance.md#security-and-access) describes this boundary.
- The webhook secret resides in AWS Secrets Manager and is retrieved at runtime. It is not embedded in Terraform configuration or public artifacts.
- REST and WebSocket clients authenticate with AWS IAM. Postman testing uses temporary authorization generated for the target environment.
- The Marquez service and database are private. Only SigV4-authenticated requests can traverse API Gateway to its internal load balancer.
- Workloads use narrowly scoped task and function roles. IAM policy templates require target account, region, bucket and alert values when rendered.
- The raw data bucket blocks public access, enables versioning and uses server-side encryption. Kinesis, SQS, DynamoDB recovery and encrypted failure queues protect the durable paths.

## Observability

Two CloudWatch dashboards support different questions. Resolve their deployed names from Terraform outputs instead of assuming an environment-specific name:

```zsh
terraform -chdir=infra output -raw cloudwatch_dashboard_name
terraform -chdir=infra output -raw realtime_observability_dashboard_name
```

| Dashboard | Operational focus |
| --- | --- |
| Pipeline observability output | End-to-End pipeline: Kinesis, Firehose, Glue, MWAA, dbt, Soda and analytical failures |
| Realtime observability output | Realtime state: processor errors, iterator age, processing latency, WebSocket delivery and simulator activity |

Alarms cover pipeline task failures, throttling, Firehose delivery, processor errors and throttles, iterator age, live processing latency, WebSocket-delivery failures, collector health, missing lineage events and client-side lineage-emission failures. Operational validation is complete only when current state advances, monitoring clients receive updates and the relevant alarms are `OK`.

## Deployment and Configuration

Terraform owns the AWS infrastructure. A clone supplies target-specific configuration through one ignored local file:

```text
.env                                      target-specific inputs entered once
config/deployment.defaults.json           tracked stable project defaults
infra/deployment.auto.tfvars.json         generated application Terraform inputs
```

The tracked `.env.example` contains placeholders only. The renderer derives shared settings such as patient access policy and the Terraform state prefix. Generated MWAA workflow definitions, Terraform state, secrets, endpoint identifiers and deployment-specific values remain local to the target environment. Setup and deployment checks are documented in [operations-runbook.md](operations-runbook.md).

## Trade-Offs

- The project prioritizes explainable, observable AWS-native services over minimizing component count.
- The dashboards use synthetic data and are not regulated clinical systems; they do not replace certified monitoring or clinical decision-support tools.
- The portfolio environment retains short operational log and database-backup periods to control cost. A production deployment would require formal retention, recovery, compliance and clinical-safety review.
