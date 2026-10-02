---
title: Documentation Index
description: Find deployment, operational, analytical and historical project documentation.
last_updated: 2026-10-02
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
| [Building an End-to-End Healthcare Realtime Monitoring Platform on Amazon Web Services (AWS)](building-healthcare-realtime-monitoring.md) | Technical article draft requiring editorial approval |
| [Data Governance](data-governance.md) | Schema, freshness, lineage and replay controls |
| [Demo Guide](demo-guide.md) | Start, inspect and shut down a synthetic demo |
| [Deployment Guide](deployment.md) | Configuration, packages and deployment validation |
| [End-to-End Test Plan](e2e-test-plan.md) | Approved scenarios, failure modes and run evidence |
| [Environments](environments.md) | Environment selection and account isolation |
| [Externally Managed Prerequisites](external-prerequisites.md) | Resources managed outside application Terraform |
| [Fast Healthcare Interoperability Resources (FHIR) Setup Tasks](fhir-setup-tasks.md) | Load the synthetic cohort and register the subscription |
| [Infrastructure Lifecycle](infrastructure-lifecycle.md) | Bootstrap, converge and tear down infrastructure |
| [Realtime Load Testing](load-testing.md) | Run isolated throughput and latency verification |
| [Model Predictions](model-predictions.md) | Score with an approved immutable model |
| [Model Training](model-training.md) | Train and evaluate the nonclinical proxy model |
| [Operations Runbook](operations-runbook.md) | Verify health, diagnose failures and perform recovery |
| [Power BI Athena Connection](power-bi-connection.md) | Connect Power BI Desktop to Athena |
| [Quality Checks](quality-checks.md) | Hook policies, pinned tools and review gates |
| [First Deployment Quickstart](quickstart.md) | Prepare a clone and deploy a development stack |
| [Release Checklist](release-checklist.md) | Historical release checklist and repeatable release gate |
| [v1.0.0 Release Notes](release-notes-v1.0.0.md) | Historical release evidence; does not certify later changes |
| [v1.0.1 Release Notes](release-notes-v1.0.1.md) | Historical release evidence; does not certify later changes |
| [Technology Inventory](technology-inventory.md) | Implemented technologies, roles and paths |

## Local Evidence and Reporting

End-to-End (E2E) run reports remain ignored under `artifacts/e2e/`. Documentation review evidence remains in ignored `.documentation_review.json`. A private Power BI report guide and the Power BI binary are local artifacts outside the tracked documentation inventory; [Athena connection](power-bi-connection.md) is the public reference.

## Format Review

Metadata, headings and syntax are prepared for verification. Adoption requires the complete manual document and workflow review plus passing real hooks. Use no hard wrapping; preserve established names. Keep architecture source and its generated image under `docs/architecture/`.
