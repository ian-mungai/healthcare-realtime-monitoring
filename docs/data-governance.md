---
title: "Data Governance"
description: "Look up schema validation, event identity, freshness, retention and lineage controls."
last_updated: 2026-10-07
audience: [developer, operator]
---

# Data Governance

For developers and operators: look up schema validation, event identity, freshness, retention and lineage controls.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Purpose and Scope](#purpose-and-scope)
- [Dataset Inventory](#dataset-inventory)
- [Standards and Schema](#standards-and-schema)
- [Quality Gates](#quality-gates)
- [Provider and Feature Provenance](#provider-and-feature-provenance)
- [Deduplication and Ordering](#deduplication-and-ordering)
- [Failure Handling and Replay](#failure-handling-and-replay)
- [Lineage](#lineage)
- [Security and Access](#security-and-access)
- [Retention and Recovery](#retention-and-recovery)
- [Operational Evidence](#operational-evidence)

## Terminology

- **ACVPU**: alert, confusion, voice, pain, unresponsive, the consciousness scale NEWS2 uses.
- **AVPU**: alert, voice, pain, unresponsive, the scale without confusion.
- **API**: application programming interface.
- **AES**: Advanced Encryption Standard.
- **ARN**: Amazon Resource Name.
- **AWS**: Amazon Web Services.
- **BIDMC**: Beth Israel Deaconess Medical Center.
- **CI**: continuous integration.
- **DLQ**: dead-letter queue.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **HTTP**: HyperText Transfer Protocol.
- **IAM**: Identity and Access Management.
- **ID**: identifier.
- **ISO**: International Organization for Standardization.
- **JSON**: JavaScript Object Notation.
- **JSONL**: JSON Lines.
- **KMS**: Key Management Service.
- **LOINC**: Logical Observation Identifiers Names and Codes.
- **MWAA**: Managed Workflows for Apache Airflow.
- **NAT**: network address translation.
- **NEWS2**: National Early Warning Score 2.
- **NPPES**: National Plan and Provider Enumeration System.
- **RDS**: Relational Database Service.
- **REST**: Representational State Transfer.
- **SCD2**: type 2 slowly changing dimension.
- **SQS**: Simple Queue Service.
- **VPC**: virtual private cloud.
- **UI**: user interface.
- **URL**: uniform resource locator.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<PROJECT_DATA_BUCKET>`: project data bucket for the selected environment or example.

## Purpose and Scope

This document describes the controls applied to realtime vital-sign events and the analytical datasets produced by the healthcare realtime monitoring pipeline. The portfolio data is synthetic Synthea data combined with Beth Israel Deaconess Medical Center (BIDMC) waveform-derived measurements; it is not production patient data and must not be represented as such.

The governed path is:

```text
BIDMC measurements -> FHIR Observation -> Kinesis -> realtime serving
                                      \-> S3 raw -> Glue/Iceberg -> dbt -> Soda
```

## Dataset Inventory

| Dataset | System | Purpose |
| --- | --- | --- |
| `seed/synthea/fhir/` | Amazon S3 | Synthetic Synthea bundles uploaded for the Fast Healthcare Interoperability Resources (FHIR) setup task's cohort load |
| `raw/fhir_observations/` | Amazon S3 | Immutable normalized FHIR vital-event landing area |
| `${ATHENA_SOURCE_DATABASE}.${ATHENA_PROCESSED_TABLE}` | Glue Catalog / Iceberg | Validated, deduplicated observations |
| `${ATHENA_DBT_DATABASE}.${DBT_STAGING_TABLE}` | Athena / dbt | Clean analytical staging model |
| `${ATHENA_DBT_DATABASE}.${DBT_FACT_OBSERVATIONS_TABLE}` | Athena / dbt | Keyed vital-sign measurement fact |
| `${ATHENA_DBT_DATABASE}.${DBT_DIM_PATIENT_TABLE}` | Athena / dbt | Conformed synthetic patient dimension |
| `${ATHENA_DBT_DATABASE}.${DBT_DIM_ENCOUNTER_TABLE}` | Athena / dbt | Encounter analysis-window dimension |
| `${ATHENA_DBT_DATABASE}.${DBT_DIM_PROVIDER_TABLE}` | Athena / dbt | Synthetic effective-dated provider dimension |
| `${ATHENA_DBT_DATABASE}.${DBT_DIM_OBSERVATION_TYPE_TABLE}` | Athena / dbt | Conformed Logical Observation Identifiers Names and Codes (LOINC) observation-type dimension |
| `${ATHENA_DBT_DATABASE}.${DBT_DIM_DATE_TABLE}` | Athena / dbt | Observation calendar dimension |
| `${ATHENA_DBT_DATABASE}.${DBT_ENCOUNTER_FEATURES_TABLE}` | Athena / dbt | Encounter features and synthetic deterioration proxy label |
| `fact_encounter_news2` | Athena / dbt and the local Postgres warehouse | NEWS2 at the end of each encounter's feature window, the analysis benchmark |
| `${ATHENA_DBT_DATABASE}.${DBT_ML_TRAINING_TABLE}` | Athena / dbt | Versioned model features, proxy label and patient-grouped split |
| `${ATHENA_DBT_DATABASE}.${DBT_ML_SCORING_TABLE}` | Athena / dbt | Inference-safe features for completed fixed feature windows |
| `ml/model_artifacts/` | Amazon S3 | Checksummed immutable model, manifest and evaluation artifacts |
| `ml/predictions/` | Amazon S3 | Model-version-partitioned prediction records |
| `${ATHENA_ML_DATABASE}.${ATHENA_PREDICTIONS_PUBLISHED_TABLE}` | Glue Catalog / Athena | Terraform-owned external prediction table |
| `${ATHENA_DBT_DATABASE}.${DBT_ML_PREDICTIONS_SERVING_TABLE}` | Athena / dbt | Versioned prediction history |
| `${ATHENA_DBT_DATABASE}.${DBT_ML_PREDICTIONS_LATEST_TABLE}` | Athena / dbt | Predictions restricted to the approved model version |
| `${LATEST_VITALS_TABLE}` | DynamoDB | Latest accepted realtime state by patient |
| `quarantine/fhir_observations/` | Amazon S3 | Rejected analytical records with reasons |
| `raw.fhir_patients`, `raw.patient_payer_history`, `raw.facilities` and `raw.admissions` | Local Postgres warehouse | Cohort reference rows: synthetic demographics (birth date, gender, race, ethnicity, marital status and state; no names or address lines), payer periods, Synthea hospitals and simulated admissions with the synthetic attending's NPI (Local Stack) |
| `reference/cohort/` (`fhir_patients`, `patient_payer_history`, `facilities`, `admissions`, `patient_split_groups`) | Amazon S3 / Glue Catalog | Cohort reference rows written daily by the FHIR setup task as JSON lines, read through Glue tables in the source database |
| `dim_patient_version`, `dim_facility`, `dim_unit`, `fact_admissions`, `fact_encounter_minute_features` and `fact_encounter_trend_features` | Athena / dbt and the local Postgres warehouse | Cohort reference models, built when `cohort_reference_enabled` is true: daily on AWS and in the local warehouse |
| `${ATHENA_SOURCE_DATABASE}.${ATHENA_QUARANTINE_TABLE}` | Glue Catalog / Athena | Queryable view of quarantined records |
| `metrics/glue/` | Amazon S3 | Per-run candidate, valid and rejected counts |
| `glue/temp/` and `glue/spark-ui/` | Amazon S3 | Glue job temporary files and Spark UI event logs, kept in the project bucket so the job role needs no other bucket |

The repository owner operates the portfolio datasets and infrastructure. Formal business owners and data stewards are not encoded in repository metadata.

## Standards and Schema

FHIR R4 `Observation` resources are transformed into versioned realtime payloads and analytical measurement rows. Current schema `1.2` payloads require a nonempty observation identifier (ID), patient ID, encounter ID, source, International Organization for Standardization (ISO)-8601 event timestamp and at least one supported numeric vital. Schema `1.2` adds the optional temperature, inhaled oxygen concentration and consciousness fields; schema `1.1` payloads, without them, remain valid. Legacy schema `1.0` payloads remain replay-compatible without an encounter ID.

Supported LOINC codes are:

The machine-readable source of truth is [`config/vital_signs.json`](../config/vital_signs.json). Independently deployed components retain local constants and contract tests verify that their LOINC codes, units, names and validation ranges match this catalog.

| LOINC | Measurement | Analytical range |
| --- | --- | --- |
| `8867-4` | Heart rate | 20-250 |
| `9279-1` | Respiratory rate | 4-80 |
| `2708-6` | Oxygen saturation | 50-100 |
| `8480-6` | Systolic blood pressure | 50-260 |
| `8462-4` | Diastolic blood pressure | 30-180 |
| `8310-5` | Body temperature (degrees Celsius) | 32-43 |
| `3150-0` | Inhaled oxygen concentration (%) | 21-100 |
| `67775-7` | Level of responsiveness (ACVPU ordinal) | 0-4 |

Consciousness arrives as a coded FHIR answer and is stored as an ordinal: A (Alert, `LA9340-6`) 0, C (Confused, `LA6560-2`) 1, V (Verbal, `LA17108-4`) 2, P (Painful, `LA17107-6`) 3 and U (Unresponsive, `LA9343-0`) 4. LOINC `67775-7` is the AVPU code; its answer list has no confused answer, so C uses LOINC's own `LA6560-2`, the one answer outside that list. No LOINC code carries an ACVPU answer list. `80288-4` (Level of consciousness) lists Lethargic, Obtunded and Stuporous instead of Voice and Pain. The webhook rejects any other answer code.

The realtime validator permits systolic values through 300 and diastolic values through 200. This intentionally broader ingestion boundary prevents obviously invalid events while the analytical layer applies the stricter portfolio-quality ranges above.

## Quality Gates

Glue classifies every analytical measurement candidate before writing it. Records are rejected for:

- missing observation, patient or LOINC identifiers;
- unsupported LOINC codes;
- missing values or effective timestamps; or
- physiological range violations.

Rejected records are appended to `s3://<PROJECT_DATA_BUCKET>/quarantine/fhir_observations/` with `rejection_reason` and `quarantined_at`. The external Glue table `${ATHENA_SOURCE_DATABASE}.${ATHENA_QUARANTINE_TABLE}` exposes those JavaScript Object Notation (JSON) records to Athena. Per-run counts are appended under `metrics/glue/`.

Great Expectations validates the processed Iceberg table for required fields, allowed LOINC codes and uniqueness of `observation_id` plus `loinc_code`. Every automated dbt build applies not-null tests to the source keys of the processed observation and published prediction tables, then model-level not-null, uniqueness, relationship and accepted-value tests, including singular tests for the `DBT_FACT_OBSERVATIONS_TABLE` compound grain and provider SCD2 validity. Soda contracts independently verify that the staging, fact, dimension and feature tables are nonempty, satisfy their key constraints, preserve the fact-table compound grain and use valid binary labels. The conformed dimensions and bus matrix are defined in [analytics-star-schema.md](analytics-star-schema.md). Both sources also declare a 26-hour freshness warning on their load timestamps (`received_at` and `scored_at`), reported by `dbt source freshness`.

## Provider and Feature Provenance

The committed provider history is a synthetic National Plan and Provider Enumeration System (NPPES)-compatible fixture. It contains no assertion about real clinicians and deterministic encounter assignments are explicitly flagged as synthetic. Its generator checked every NPI against the NPPES NPI Registry (no real clinician anywhere in the US) and every name against Washington clinicians on Oct 7 2026; it keeps only counts and attempt numbers, never a matched clinician's number or name. An NPI unassigned on that date can still be issued later. A local utility can merge a normalized NPPES snapshot into effective-dated history, but real provider extracts and generated histories must remain outside the public repository.

The encounter feature table uses the first fixed 15 minutes for features and the following fixed 15 minutes for the outcome proxy. The boundary is computable while an encounter is in progress and does not depend on its eventual end time. The outcome window produces a versioned deterioration proxy that requires repeated observations of the same vital beyond a National Early Warning Score 2 (NEWS2) extreme threshold, reducing sensitivity to isolated synthetic measurements. This proxy supports pipeline demonstration only and is not a diagnosis, a validated clinical outcome or approved training data for clinical use.

The simulator creates fresh encounter identifiers at task startup. Runs planned to cover the full 30-minute window count each patient's scenario-tagged encounters in HAPI FHIR and select the less frequent normal or deterioration-proxy scenario. Ties use `SIMULATOR_SCENARIO_SEED` and the patient identifier or a random choice. Shorter planned runs use the seed or random choice without counting or tagging history.

Tags and logs record startup assignments, not completed analytical labels. Interrupted or concurrent runs can affect the counts. Transformations remain confined to the outcome window and the analytical split stays grouped by patient to prevent leakage. Actual window observations, class diversity in both partitions and no patient leakage determine readiness; the [star-schema reference](analytics-star-schema.md#feature-and-label-construction) defines these boundaries.

The training dataset excludes ineligible encounters and assigns complete patient histories to either training or testing. Its feature schema, label definition, split rule and source-row fingerprint are recorded with every baseline model artifact. Generated model files remain under the ignored `build/` directory unless a reviewed private artifact store is configured.

Historical quality checkpoint before the star-schema expansion, verified on Sep 3 2026:

- Great Expectations: 15 of 15 expectations passed.
- Soda: 26 of 26 contract checks passed across four datasets.
- Lineage tests: 41 of 41 passed.

## Deduplication and Ordering

The analytical identity is the compound key `observation_id` plus `loinc_code`. Glue removes duplicates from each incoming batch and uses the same key in an Iceberg `MERGE`, updating existing rows and inserting new rows.

Realtime state is keyed by `patient_id`. DynamoDB compares the incoming timestamp against the stored timestamp for each vital present in the event and accepts equal or later timestamps. It preserves vitals absent from a partial event and removes the legacy global timestamp fields. A separate observation-ID claim prevents duplicate processing; an event containing any stale vital is skipped as a whole, because all included freshness predicates must pass. Equal timestamps are accepted; this does not independently merge the fresher fields of a mixed event. See [`write_latest_vitals`](../services/vitals_stream_processor/handler.py). Patient WebSocket delivery is attempted only after the latest-state write succeeds.

## Failure Handling and Replay

The processor separates permanent from retryable failures. A record that fails validation (unsupported schema version, malformed JSON, missing fields, out-of-range vitals) is rejected at once, logged and counted in the `PermanentRecordsRejected` metric; it is never retried or replayed. A retryable failure, such as a failed DynamoDB write, is reported as a batch item failure. Lambda retries it up to three times, splitting the batch to isolate it, then sends the batch details to the encrypted failure queue provisioned by the realtime failure-handling module.

The replay Lambda reads each failure message, retrieves the original sequence range from the main vitals stream and republishes it with an incremented `_replay_attempt`. Automatic replay is limited to one attempt and a message reaches the module-managed replay dead-letter queue in one of two ways:

1. **Terminal record:** a record already at the replay limit or one that cannot be decoded, is written straight to the dead-letter queue with its reason, sequence number and original data.
2. **Failed replay:** a failure message the Lambda cannot process moves to the dead-letter queue after five failed Simple Queue Service (SQS) receives. This includes every failure from the isolated load-test stream, because the replay Lambda accepts only the main stream and never republishes load-test records.

Both queues retain messages for 14 days and use SQS-managed server-side encryption.

### GOV-1. Inspect Before Redrive

Operators MUST inspect and correct records in the replay dead-letter queue (DLQ) before manual redrive.

Why: redriving an unresolved failure can repeat the same error.

- Do: diagnose the rejection and validate corrected synthetic records.
- Don't: redrive a failure merely to empty the queue.

Analytical quarantine recovery is separate from SQS transport recovery. Operators query the quarantine table, export a bounded set with `scripts/quarantine/manage_quarantine.py`, correct and validate the JSON Lines (JSONL) file, then explicitly confirm publication to Kinesis. Corrected records retain their analytical identity so Iceberg replay remains idempotent.

## Lineage

OpenLineage events are sent to the configured shared HyperText Transfer Protocol (HTTP) collector. When no collector URL is configured, they are stored under `s3://<PROJECT_DATA_BUCKET>/lineage/openlineage/`. Instrumented Glue, Athena, Great Expectations, dbt and Soda jobs emit `START` and either `COMPLETE` or `FAIL` with a shared run ID. The model-scoring job publishes predictions but does not emit its own lifecycle events; dbt records its prediction sources and serving models.

The verified lineage chain is:

```text
S3 normalized FHIR vital events
  -> Glue processed observations
  -> Athena quality validation
  -> dbt staging, fact, dimensions, encounter features and model inputs
  -> approved-model prediction publication and serving views
  -> Soda contract validation
```

Great Expectations also emits an independent quality lineage edge from processed observations to its validation result. The common job namespace is `healthcare-realtime-monitoring`.

## Security and Access

- The data bucket blocks public access, enables versioning and uses AES-256 server-side encryption.
- The HAPI FHIR load balancer accepts HTTP only from the network address translation (NAT) gateway, as configured in [the Terraform root](../infra/main.tf). Cohort loading and subscription registration run inside the virtual private cloud (VPC) and need no operator address.
- The Kinesis stream uses Amazon Web Services (AWS)-managed Key Management Service (KMS) encryption.
- The latest-vitals DynamoDB table has point-in-time recovery enabled.
- application programming interface (API) Gateway Representational State Transfer (REST) and WebSocket connection routes use AWS Identity and Access Management (IAM) authorization where configured.
- The FHIR webhook uses a secret header; secret handling follows [GOV-2](#gov-2-keep-operational-values-private).
- Elastic Container Service (ECS) tasks and Lambda functions use workload-specific IAM roles scoped to required services and paths.
- Every resource that holds data carries a `DataClassification` tag: `Synthetic` for the pipeline data stores, `Internal` for the WebSocket connection table (it stores caller IAM principal ARNs), the lineage database and the Terraform state bucket. Project, environment and ownership tags come from the AWS provider's default tags.
- Elastic Container Registry (ECR) image tags used for deployments are generated from the source commit, recorded in private configuration after publishing and validated as immutable `sha-*` tags.

### GOV-2. Keep Operational Values Private

Terraform state, credentials, webhook secrets, alert addresses, connection IDs and signed authorization headers MUST remain private.

Why: operational values are outside the portfolio evidence boundary.

- Do: use placeholders in shareable evidence.
- Don't: publish state, credentials or signed requests.

<details>
<summary>Old Patterns</summary>

Commit `53ff5b1` permits the NAT gateway and configured operator network ranges to reach HAPI. The task-based cohort setup introduced in commit `b9db2e8` supplies only the NAT gateway to the HAPI module. Operator-machine access is outside that implemented configuration.

</details>

## Retention and Recovery

CloudWatch log groups for HAPI, dbt, Soda, the vitals simulator and the FHIR setup task retain logs for 14 days. SQS failure and replay-DLQ messages are retained for 14 days. HAPI Relational Database Service (RDS) automated backups are retained for one day. DynamoDB point-in-time recovery protects the latest-vitals table.

The processed Iceberg table uses Glue managed table optimizers once `ENABLE_ICEBERG_TABLE_OPTIMIZERS=true` is set after its first Glue run: compaction, snapshot retention (snapshots older than seven days expire while at least three are kept) and orphan-file deletion after seven days. dbt rebuilds its Iceberg tables on each run, so they need no separate maintenance.

The versioned S3 data bucket has no lifecycle expiration policy. Raw, processed, quarantine, metrics, lineage and Athena-result objects therefore remain until explicitly removed or a reviewed lifecycle policy is introduced.

## Operational Evidence

Evidence for a governed release should include:

- successful Managed Workflows for Apache Airflow (MWAA) Serverless workflow and task states;
- Great Expectations and Soda pass summaries;
- matching OpenLineage lifecycle events and run IDs;
- Glue valid/rejected metrics and quarantine location;
- healthy CloudWatch dashboards and alarms;
- controlled failure and replay evidence; and
- Terraform convergence and continuous integration (CI) success.

### GOV-3. Redact Evidence

Evidence MUST use synthetic identifiers and redact secrets, credentials, signed headers, email addresses and account-specific sensitive values.

Why: verification does not authorize disclosure of operational or personal data.

- Do: review a redacted copy before sharing.
- Don't: treat raw terminal output as public evidence.
