# Data Governance

## Purpose and scope

This document describes the controls applied to realtime vital-sign events and the analytical datasets produced by the healthcare realtime monitoring pipeline. The portfolio data is synthetic Synthea data combined with BIDMC waveform-derived measurements; it is not production patient data and must not be represented as such.

The governed path is:

```text
BIDMC measurements -> FHIR Observation -> Kinesis -> realtime serving
                                      \-> S3 raw -> Glue/Iceberg -> dbt -> Soda
```

## Dataset inventory

| Dataset | System | Purpose |
| --- | --- | --- |
| `raw/fhir_observations/` | Amazon S3 | Immutable raw FHIR event landing area |
| `healthcare_realtime.processed_fhir_observations` | Glue Catalog / Iceberg | Validated, deduplicated observations |
| `healthcare_realtime_dbt.stg_fhir_observations` | Athena / dbt | Clean analytical staging model |
| `healthcare_realtime_dbt.fact_observations` | Athena / dbt | Observation-level fact model |
| `healthcare_realtime_dbt.dim_patient` | Athena / dbt | Patient-level observation summary |
| `healthcare_realtime_dbt.dim_observation_type` | Athena / dbt | LOINC observation-type summary |
| `healthcare-realtime-latest-vitals` | DynamoDB | Latest accepted realtime state by patient |
| `quarantine/fhir_observations/` | Amazon S3 | Rejected analytical records with reasons |
| `metrics/glue/` | Amazon S3 | Per-run candidate, valid, and rejected counts |

Formal business owners and data stewards are not currently encoded in repository metadata. Until that is added, the repository owner operates the portfolio datasets and infrastructure.

## Standards and schema

FHIR R4 `Observation` resources are transformed into versioned realtime payloads and analytical measurement rows. Realtime payloads require schema version `1.0`, a nonempty observation ID, patient ID, source, ISO-8601 event timestamp, and at least one supported numeric vital.

Supported LOINC codes are:

| LOINC | Measurement | Analytical range |
| --- | --- | --- |
| `8867-4` | Heart rate | 20-250 |
| `9279-1` | Respiratory rate | 4-80 |
| `2708-6` | Oxygen saturation | 50-100 |
| `8480-6` | Systolic blood pressure | 50-260 |
| `8462-4` | Diastolic blood pressure | 30-180 |

The realtime validator permits systolic values through 300 and diastolic values through 200. This intentionally broader ingestion boundary prevents obviously invalid events while the analytical layer applies the stricter portfolio-quality ranges above.

## Quality gates

Glue classifies every analytical measurement candidate before writing it. Records are rejected for:

- missing observation, patient, or LOINC identifiers;
- unsupported LOINC codes;
- missing values or effective timestamps; or
- physiological range violations.

Rejected records are appended to `s3://<project-data-bucket>/quarantine/fhir_observations/` with `rejection_reason` and `quarantined_at`. Per-run counts are appended under `metrics/glue/`.

Great Expectations validates the processed Iceberg table for required fields, allowed LOINC codes, and uniqueness of `observation_id` plus `loinc_code`. dbt applies model-level not-null, uniqueness, and accepted-value tests. Soda contracts independently verify that the staging, fact, and dimension tables are nonempty and satisfy their column constraints.

Verified quality checkpoint on 2026-09-03:

- Great Expectations: 15 of 15 expectations passed.
- Soda: 26 of 26 contract checks passed across four datasets.
- Lineage tests: 41 of 41 passed.

## Deduplication and ordering

The analytical identity is the compound key `observation_id` plus `loinc_code`. Glue removes duplicates from each incoming batch and uses the same key in an Iceberg `MERGE`, updating existing rows and inserting new rows.

Realtime state is keyed by `patient_id`. DynamoDB accepts an update only when its event timestamp is newer than the stored `_event_timestamp_epoch_ms`; duplicate and stale events are ignored. Patient WebSocket delivery is attempted only after the latest-state write succeeds.

## Failure handling and replay

Kinesis batch item failures are sent to the encrypted `healthcare-realtime-vitals-failures-development` SQS queue. The replay Lambda retrieves the original Kinesis sequence range and republishes it with an incremented `_replay_attempt`.

Automatic replay is limited to one attempt. After five failed SQS receives, the message moves to `healthcare-realtime-vitals-replay-dlq-development`. Both queues retain messages for 14 days and use SQS-managed server-side encryption. Operators must inspect and correct records in the replay DLQ before any manual redrive.

## Lineage

OpenLineage events are stored under `s3://<project-data-bucket>/lineage/openlineage/`. Each job emits `START` and either `COMPLETE` or `FAIL` with a shared run ID.

The verified lineage chain is:

```text
S3 raw FHIR observations
  -> Glue processed observations
  -> Athena quality validation
  -> dbt staging, fact, and dimensions
  -> Soda contract validation
```

Great Expectations also emits an independent quality lineage edge from processed observations to its validation result. The common job namespace is `healthcare-realtime-monitoring`.

## Security and access

- The data bucket blocks public access, enables versioning, and uses AES-256 server-side encryption.
- The Kinesis stream uses AWS-managed KMS encryption.
- The latest-vitals DynamoDB table has point-in-time recovery enabled.
- API Gateway REST and WebSocket connection routes use AWS IAM authorization where configured.
- The FHIR webhook uses a secret header; secret values must never be committed or included in evidence.
- ECS tasks and Lambda functions use workload-specific IAM roles scoped to required services and paths.
- ECR image tags used for deployments are supplied explicitly; the simulator requires immutable `sha-*` tags.

Terraform state, credentials, webhook secrets, alert addresses, connection IDs, and signed authorization headers are not portfolio evidence and must remain private.

## Retention and recovery

CloudWatch log groups for HAPI, dbt, Soda, and the vitals simulator retain logs for 14 days. SQS failure and replay-DLQ messages are retained for 14 days. HAPI RDS automated backups are retained for one day. DynamoDB point-in-time recovery protects the latest-vitals table.

The versioned S3 data bucket currently has no lifecycle expiration policy. Raw, processed, quarantine, metrics, lineage, and Athena-result objects therefore remain until explicitly removed or a reviewed lifecycle policy is introduced.

## Operational evidence

Evidence for a governed release should include:

- successful MWAA Serverless workflow and task states;
- Great Expectations and Soda pass summaries;
- matching OpenLineage lifecycle events and run IDs;
- Glue valid/rejected metrics and quarantine location;
- healthy CloudWatch dashboards and alarms;
- controlled failure and replay evidence; and
- Terraform convergence and CI success.

Evidence must use synthetic identifiers and redact secrets, credentials, signed headers, email addresses, and other account-specific sensitive values.
