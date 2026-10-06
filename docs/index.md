---
title: Documentation Index
description: Find deployment, operational, analytical and historical project documentation.
last_updated: 2026-10-06
audience: [developer, operator]
---

# Documentation Index

For developers and operators of the synthetic portfolio system: select the document for your task. These files are the editable sources; generated diagrams and local evidence identify their sources separately.

## Terminology

- **AWS**: Amazon Web Services.
- **BI**: business intelligence.
- **E2E**: end-to-end.
- **FHIR**: Fast Healthcare Interoperability Resources.

## Guides and References

| Document | Purpose |
| --- | --- |
| [Analytics Star Schema](analytics-star-schema.md) | Grains, joins and conformed analytical dimensions |
| [Architecture](architecture.md) | System paths, security boundaries and recovery |
| [Deployment Stages and Recovery](bootstrap.md) | Deployment stages and recovery checkpoints |
| [Data Governance](data-governance.md) | Schema, freshness, lineage and replay controls |
| [Demo Guide](demo-guide.md) | Start, inspect and shut down a synthetic demo |
| [Deployment Guide](deployment.md) | Configuration, packages and deployment validation |
| End-to-End Test Plan | Approved scenarios, failure modes and run evidence |
| [Environments](environments.md) | Environment selection and account isolation |
| [Externally Managed Prerequisites](external-prerequisites.md) | Resources managed outside application Terraform |
| [Fast Healthcare Interoperability Resources (FHIR) Setup Tasks](fhir-setup-tasks.md) | Load the synthetic cohort and register the subscription |
| [Infrastructure Lifecycle](infrastructure-lifecycle.md) | Bootstrap, converge and tear down infrastructure |
| [Realtime Load Testing](load-testing.md) | Run isolated throughput and latency verification |
| [Model Predictions](model-predictions.md) | Score with an approved immutable model |
| [Model Training](model-training.md) | Train and evaluate the nonclinical proxy model |
| [Operations Runbook](operations-runbook.md) | Verify health, diagnose failures and perform recovery |
| [Power BI Athena Connection](power-bi-connection.md) | Connect Power BI Desktop to Athena |
| Quality Checks | Hook policies, pinned tools and review gates |
| [First Deployment Quickstart](quickstart.md) | Prepare a clone and deploy a development stack |
| [Release Checklist](release-checklist.md) | Historical release checklist and repeatable release gate |
| [v1.0.0 Release Notes](release-notes-v1.0.0.md) | Historical release evidence; does not certify later changes |
| [v1.0.1 Release Notes](release-notes-v1.0.1.md) | Historical release evidence; does not certify later changes |
| [Technology Inventory](technology-inventory.md) | Implemented technologies, roles and paths |

## Local Evidence and Reporting

End-to-End (E2E) run reports remain ignored under `artifacts/e2e/`. Documentation review evidence remains in ignored `.documentation_review.json`. The private Power BI report guide and the future recording procedure at `artifacts/capture/REQUIREMENT_replay_30min.md` are outside the tracked inventory but included in the authored-document format review. A future procedure remains authored documentation even when its folder also contains historical recordings. The private Power BI binary is a generated artifact; its native model and visuals remain unverified. [Athena connection](power-bi-connection.md) is the public reference.

## Format Review

Conventional Docs is adopted for this project's authored Markdown, including the ignored private Power BI report guide and future recording procedure. Complete manual document and workflow review plus passing real hooks verify metadata, anatomy, terminology, procedures, links and examples. README uses the separate Standard Readme structure; historical release records and run evidence preserve their recorded scope. Generated diagrams remain outside the authored-document format requirements.

Example verification includes manual syntax and schema-context review where native execution is unavailable. Native Power BI verification, article publication review and failed or unrun deployed checks remain open; format adoption does not certify those outcomes. Use no hard wrapping; preserve established names. Keep architecture source and its generated image under `docs/architecture/`; its documented update trigger remains in effect.
