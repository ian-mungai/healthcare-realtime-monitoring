---
title: "Deployment Stages and Recovery"
description: "Choose the deployment stage and recover from interrupted infrastructure operations."
last_updated: 2026-10-02
audience: [developer, operator]
---

# Deployment Stages and Recovery

For developers and operators: choose the deployment stage and recover from interrupted infrastructure operations.

## Terminology

- **ECR**: Elastic Container Registry.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **OIDC**: OpenID Connect.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or AWS commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Canonical First Deployment

Use the [first-deployment quickstart](quickstart.md) for a fresh clone, account or region. It is the only document that contains the complete first-deployment command sequence.

Do not combine commands from older notes or issue registers with the quickstart. Run each quickstart command separately, review every saved Terraform plan and continue only after the documented checkpoint succeeds.

## Deployment Stages

The bootstrap wrapper divides creation into four explicit stages:

| Stage | Purpose | Completion checkpoint |
| --- | --- | --- |
| `state-*` | Create protected remote state and initialize the main backend | Bootstrap backup is verified and `main-init` succeeds |
| `repositories-*` | Create Elastic Container Registry (ECR) repositories before image publication | All required repositories exist |
| `foundation-*` | Create HAPI Fast Healthcare Interoperability Resources (FHIR), storage, the FHIR setup task and the other resources needed to build the cohort-dependent application configuration; `run_fhir_setup.sh load` then seeds the cohort | `terraform -chdir=infra output -raw glue_job_name` returns a value |
| `application-*` | Create the remaining realtime, analytical, workflow and observability resources | A final Terraform plan reports `No changes` |

The wrapper renders ignored Terraform configuration from the selected `${PROJECT_ENV_FILE:-.env}` file before each stage. Do not edit `infra/deployment.auto.tfvars.json`, `infra/bootstrap/deployment.auto.tfvars.json` or `infra/backend.hcl` by hand.

## Interrupted Deployment

Terraform may create some resources before an apply fails. Correct the reported cause, then create and review a new saved plan for the same stage. Never apply the old plan after state has changed.

Use these checks before continuing:

1. Run the following command block:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh --check
   terraform -chdir=infra validate
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json
   ```

   The final plan must contain only understood changes. An unexplained replacement, deletion or permission expansion must be reviewed before apply.

## Existing State or Recreation

Do not use the first-deployment state commands when a protected state bucket or application state already exists. Follow the [infrastructure lifecycle guide](infrastructure-lifecycle.md) for state migration, guarded teardown and recreation.

Use the [operations runbook](operations-runbook.md) for service recovery, replay and routine operational checks. Use the [deployment guide](deployment.md) after local deployment when GitHub OpenID Connect (OIDC) or the optional shared OpenLineage collector is required.
