---
title: "Release Checklist"
description: "Evaluate the release gate while retaining the checked historical acceptance record."
last_updated: 2026-10-08
audience: [developer, operator]
---

# Release Checklist

For developers and operators: evaluate the release gate while retaining the checked historical acceptance record.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Scope](#scope)
- [Source and CI](#source-and-ci)
- [Infrastructure Convergence](#infrastructure-convergence)
- [Realtime Evidence](#realtime-evidence)
- [Data and Operations Evidence](#data-and-operations-evidence)
- [Model Activation](#model-activation)
- [Public-Artifact Redaction](#public-artifact-redaction)
- [v2.0.0 Release](#v200-release)
- [Release Tag](#release-tag)

## Terminology

- **API**: application programming interface.
- **AWS**: Amazon Web Services.
- **BI**: business intelligence.
- **CI**: continuous integration.
- **DSN**: data source name.
- **ECR**: Elastic Container Registry.
- **ECS**: Elastic Container Service.
- **E2E**: end-to-end.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **IAM**: Identity and Access Management.
- **MWAA**: Managed Workflows for Apache Airflow.
- **ODBC**: Open Database Connectivity.
- **OIDC**: OpenID Connect.
- **REST**: Representational State Transfer.
- **VPC**: virtual private cloud.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<API_ID>`: api id for the selected environment or example.
- `<AWS_REGION>`: aws region for the selected environment or example.
- `<PROJECT_DATA_BUCKET>`: project data bucket for the selected environment or example.

## Scope

Use this checklist to close a portfolio release of the healthcare realtime monitoring project. All published evidence must use synthetic data and replace deployment-specific values with placeholders.

The checked items and dated evidence record the v1.0.1 release. The v2.0.0 release repeated them and added the checks in [v2.0.0 release](#v200-release), which cover changes made after v1.0.1.

The portfolio release includes the completed Power BI-to-Athena connection and reporting documentation. The local `.pbix` remains outside the repository. Power BI Service publishing remains optional and private.

## Source and CI

- [x] Working tree is clean before tagging.
- [x] The release commit is on `main` and pushed to the remote.
- [x] GitHub Actions CI is green for the release commit, including Python checks, Terraform checks and container builds. Synthea validation may be skipped when its paths are unchanged.
- [x] The release notes identify the release scope without publishing account IDs, endpoint identifiers, bucket names or secret material.

## Infrastructure Convergence

- [x] `verify_reproducibility.sh` passes with identical build checksums and passing empty-account tests.
- [x] One deployment from an empty backend in a fresh region completes using `docs/quickstart.md`.
- [x] Guarded teardown completes with only documented external prerequisites and the protected state bucket remaining.
- [x] `check_prerequisites.sh post-deploy` reports every automated prerequisite passing.
- [x] `terraform -chdir=infra fmt -check -recursive` passes.
- [x] `terraform -chdir=infra validate` passes.
- [x] The rendered configuration passes `--check` and the Terraform plan is reviewed.
- [x] Each action is an intended deployment change with no unexplained replacement, deletion or permission broadening.
- [x] Only the approved saved plan is applied.
- [x] The Managed Workflows for Apache Airflow (MWAA) Serverless workflow is regenerated from deployed outputs before its changes are applied.
- [x] The post-deployment Terraform plan reports `No changes` after refresh-only reconciliation of computed values.
- [x] The main state backend is separate from application storage and the bootstrap state is backed up privately.

The portability rollout intentionally changes the Glue job arguments, MWAA workflow definition and dbt/Soda Elastic Container Service (ECS) task-definition revisions. These changes make the target bucket and region runtime configuration rather than repository constants.

## Realtime Evidence

- [x] Exactly one simulator task starts through `scripts/demo/start_vitals_demo.sh`.
- [x] The simulator is running with `scripts/demo/status_vitals_demo.sh`.
- [x] The cohort dashboard displays current measurements for every configured simulated patient.
- [x] The separate model analytics dashboard displays readiness and governance labels and remains separate from live monitoring.
- [x] Trend focus and cohort return behavior without losing other patient lines.
- [x] Representational State Transfer (REST) latest-vitals responses succeed for all ten patients with Amazon Web Services (AWS) Identity and Access Management (IAM) authorization.
- [x] Live WebSocket delivery succeeds for all ten patients with AWS IAM authorization.
- [x] Every patient event timestamp advances during the demonstration.
- [x] The simulator stops through `scripts/demo/stop_vitals_demo.sh` after evidence capture.

Detailed instructions are in [demo-guide.md](demo-guide.md).

## Data and Operations Evidence

- [x] Both Terraform-managed CloudWatch dashboards are present and their monitored services are healthy.
- [x] The realtime dashboard shows current processing, low iterator age and no sustained delivery errors.
- [x] All six realtime processing, iterator, delivery, error, throttle and replay alarms are `OK`.
- [x] Successful Glue, Athena, Great Expectations, dbt, Soda and OpenLineage validation outcomes are recorded.
- [x] MWAA remains manual-only while `ML_APPROVED_MODEL_VERSION` is empty.
- [x] The failure queue and replay dead-letter queue are empty.

Verified release evidence on Sep 16 2026: the cohort dashboard displayed current measurements for all ten configured simulated patients; the model analytics dashboard displayed all ten Athena-backed approved-model scores with encounter, feature and governance context; one MWAA Serverless run completed all nine workflow tasks successfully; and the shared collector contained successful runs for all five expected analytical lineage jobs. Deployment-specific identifiers are intentionally omitted.

Verified release evidence on Sep 17 2026: a fresh regional deployment completed from the quickstart; post-deployment prerequisites passed; GitHub OpenID Connect (OIDC) was active; CI passed; Terraform converged; all ten live patients were current with active WebSocket connections; all realtime alarms were `OK`; and both failure queues were empty. The simulator published blood pressure on its documented five-minute wall-clock cadence. A later validation deployed random per-run scenarios, created fresh encounters for all ten patients and completed a healthy first cycle. Deployment-specific identifiers are intentionally omitted.

## Model Activation

- [x] Complete 30-minute simulator sessions produce both proxy-label classes in both patient-grouped partitions.
- [x] An immutable model artifact is trained, reviewed and published.
- [x] The reviewed `ML_APPROVED_MODEL_VERSION` is set, its approved Terraform plan is applied and MWAA changes to the daily schedule.
- [x] The full workflow passes with validated model scoring, prediction refresh and populated model analytics in the fresh region.

Verified model evidence on Sep 18 2026: the patient-grouped training and test partitions both contained proxy-label classes `0` and `1`; the reviewed immutable baseline was published; the downstream scoring, prediction-refresh and Soda tasks passed independently; and a final MWAA Serverless run completed all nine workflow tasks successfully. The approved-model Athena view returned one current score for each of the ten configured patients. Fresh S3-backed OpenLineage events were present for Glue, Athena, Great Expectations, dbt and Soda. Terraform reported `No changes` after refresh-only reconciliation of computed workflow metadata. Model results remain synthetic portfolio evidence and are not clinically validated.

## Public-Artifact Redaction

Before committing screenshots, diagrams, examples or portfolio documents:

- [x] Public artifacts contain no account IDs, ARNs, Elastic Container Registry (ECR) registry URLs, bucket names, application programming interface (API) IDs, load-balancer names, endpoint URLs, connection IDs, private IPs, local usernames or email addresses.
- [x] Public artifacts contain no secrets, signed authorization headers, API keys, webhook values, Terraform state or terminal output containing them.
- [x] Environment values are replaced with reproducible placeholders such as `<AWS_REGION>`, `<PROJECT_DATA_BUCKET>` and `<API_ID>`.
- [x] Every redaction match is reviewed manually; implementation configuration is preserved.
- [x] Power BI Desktop can connect to the Athena analytical tables through the Amazon Athena Open Database Connectivity (ODBC) driver.
- [x] The local Power BI report is complete and the `.pbix` remains outside the repository.
- [x] The public release does not contain a `.pbix` binary or exported data source name (DSN).

## v2.0.0 Release

These checks cover the Fast Healthcare Interoperability Resources (FHIR) setup task inside the virtual private cloud (VPC), the scoped IAM policies and roles and the end-to-end runner added after v1.0.1.

- [x] The changed IAM templates are planned, reviewed and applied using `infra/iam/scripts/manage_policies.py`.
- [x] FHIR setup `load` and `register` pass with both reports retained under `artifacts/e2e/fhir_setup/`.
- [x] FHIR setup `reference` passes. The workflow's dbt build and Soda checks pass with the cohort reference models.
- [x] The E2E session starts with no simulator running and every scenario passes, with reports retained under `artifacts/e2e/`.
- [x] The [load test](load-testing.md) passes with its report retained.
- [x] The MWAA workflow runs Glue under its scoped role before `ENABLE_ICEBERG_TABLE_OPTIMIZERS=true` is applied through a reviewed plan.
- [x] The realtime alarms are `OK`, both failure queues are empty and no `healthcare_realtime_e2e_replay_*` policy remains on the processor role.
- [x] The deployment runs from one checkout with local Terraform state. `teardown.sh destroy-apply` removes that state once it lists no resource. The checked items above that name a state bucket or GitHub OpenID Connect (OIDC) record the v1.0.1 release; this release has neither.

Verified release evidence on Oct 8 2026, on the release code in one deployment from empty local state: FHIR setup `load`, `register` and `reference` passed; the end-to-end session passed every scenario; the isolated load test passed with no missing observation; one workflow run with an approved model completed all ten tasks, including dbt, scoring and Soda, after the Iceberg optimizers were enabled through a reviewed plan; all 12 alarms were `OK` with both failure queues empty; teardown removed every resource and the local state. The [v2.0.0 release notes](release-notes-v2.0.0.md) record the figures.

## Release Tag

Create a release tag only after CI is green, Terraform has converged and the evidence checklist is complete. The command below is the v2.0.0 record; use the new version for the next release:

```zsh
git tag -a v2.0.0 -m "Portfolio release v2.0.0"
git push origin v2.0.0
```
