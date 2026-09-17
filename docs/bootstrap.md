# Deployment Stages and Recovery

## Canonical first deployment

Use the [first-deployment quickstart](quickstart.md) for a fresh clone, account or region. It is the only document that contains the complete first-deployment command sequence.

Do not combine commands from older notes or issue registers with the quickstart. Run each quickstart command separately, review every saved Terraform plan and continue only after the documented checkpoint succeeds.

## Deployment stages

The bootstrap wrapper divides creation into four explicit stages:

| Stage | Purpose | Completion checkpoint |
| --- | --- | --- |
| `state-*` | Create protected remote state and initialize the main backend | Bootstrap backup is verified and `main-init` succeeds |
| `repositories-*` | Create ECR repositories before image publication | All required repositories exist |
| `foundation-*` | Create HAPI FHIR, storage and resources needed to build the cohort-dependent application configuration | `terraform -chdir=infra output -raw glue_job_name` returns a value |
| `application-*` | Create the remaining realtime, analytical, workflow and observability resources | A final Terraform plan reports `No changes` |

The wrapper renders ignored Terraform configuration from `.env` before each stage. Do not edit `infra/deployment.auto.tfvars.json`, `infra/bootstrap/deployment.auto.tfvars.json` or `infra/backend.hcl` by hand.

## Interrupted deployment

Terraform may create some resources before an apply fails. Correct the reported cause, then create and review a new saved plan for the same stage. Never apply the old plan after state has changed.

Use these checks before continuing:

```zsh
./scripts/infrastructure/render_project_config.sh --check
terraform -chdir=infra validate
terraform -chdir=infra plan
```

The final plan must contain only understood changes. An unexplained replacement, deletion or permission expansion must be reviewed before apply.

## Existing state or recreation

Do not use the first-deployment state commands when a protected state bucket or application state already exists. Follow the [infrastructure lifecycle guide](infrastructure-lifecycle.md) for state migration, guarded teardown and recreation.

Use the [operations runbook](operations-runbook.md) for service recovery, replay and routine operational checks. Use the [deployment guide](deployment.md) after local deployment when GitHub OIDC or the optional shared OpenLineage collector is required.
