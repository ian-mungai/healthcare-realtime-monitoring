---
title: "Model Predictions"
description: "Score encounter features with an approved immutable model and inspect governed results."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Model Predictions

For developers and operators: score encounter features with an approved immutable model and inspect governed results.

## Terminology

- **DAG**: directed acyclic graph.
- **AWS**: Amazon Web Services.
- **MWAA**: Managed Workflows for Apache Airflow.
- **SHA**: Secure Hash Algorithm.
- **UTC**: Coordinated Universal Time.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<REVIEWED_MODEL_VERSION>`: reviewed model version for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or AWS commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Scope

The prediction datasets expose synthetic deterioration proxy scores for portfolio analytics. They are not clinically validated and must not be used for patient care.

## Score With a Published Model

Select an exact version-named model prefix rather than resolving a mutable `latest` pointer:

1. Run the following command block:

   ```zsh
   set -a
   source "${PROJECT_ENV_FILE:-.env}"
   set +a
   export DATA_BUCKET_NAME="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"
   ./scripts/infrastructure/render_project_config.sh --check
   export ATHENA_DBT_DATABASE="$(jq -r '.dbt_database_name' infra/deployment.auto.tfvars.json)"
   export ATHENA_ML_DATABASE="$(jq -r '.ml_database_name' infra/deployment.auto.tfvars.json)"
   export ATHENA_PREDICTIONS_PUBLISHED_TABLE="$(jq -r '.ml_predictions_published_table_name' infra/deployment.auto.tfvars.json)"
   export DBT_ML_SCORING_TABLE="$(jq -r '.dbt_ml_scoring_table_name' infra/deployment.auto.tfvars.json)"
   export ML_APPROVED_MODEL_VERSION="<REVIEWED_MODEL_VERSION>"

   .venv/bin/python -m jobs.ml.score_logistic_regression \
     --model-s3-uri "s3://${DATA_BUCKET_NAME}/ml/model_artifacts/${ML_APPROVED_MODEL_VERSION}" \
     --predictions-database "$ATHENA_ML_DATABASE" \
     --predictions-table "$ATHENA_PREDICTIONS_PUBLISHED_TABLE" \
     --publish-s3
   ```

   The scorer verifies the model and manifest Secure Hash Algorithm (SHA)-256 metadata, checks the feature order, requires an evaluated threshold, scores without retraining and writes the selected model-version partition idempotently.

2. Confirm scoring completes without checksum, feature-schema or threshold errors. Verify the published partition names the selected immutable model version and the subsequent dbt prediction refresh and Soda checks pass.

## Athena Presentation

- `${ATHENA_DBT_DATABASE}.${DBT_ML_PREDICTIONS_SERVING_TABLE}` retains versioned scoring history.
- `${ATHENA_DBT_DATABASE}.${DBT_ML_PREDICTIONS_LATEST_TABLE}` presents only the Terraform-configured approved model version for reporting.
- `proxy_risk_band` uses `baseline_proxy` and `elevated_proxy`; it does not represent a diagnosis.
- `prediction_scope` and `is_clinically_validated` prevent the analytical output from being presented as a clinical system.

## Daily Orchestration

The native Airflow directed acyclic graph (DAG) and generated Managed Workflows for Apache Airflow (MWAA) Serverless workflow run this sequence each day at `02:00` Coordinated Universal Time (UTC):

```text
dbt feature build -> approved-model scoring -> prediction-view refresh -> Soda freshness and contract checks
```

The scorer reads `${ATHENA_DBT_DATABASE}.${DBT_ML_SCORING_TABLE}`, which does not require a completed outcome window or training label. It resolves the exact artifact from `ML_APPROVED_MODEL_VERSION`, never a mutable `latest` pointer and does not retrain. Soda fails the workflow when the newest `scored_at` is 26 hours old or older.

The separate Streamlit model analytics dashboard reads `${DBT_ML_PREDICTIONS_LATEST_TABLE}` through Athena and shows one latest prediction per patient. It combines each score with its encounter and feature-window vital summaries, ranks the cohort by proxy probability and displays the approved model, decision threshold, schema, label definition, freshness, prediction scope and clinical-validation status. Its launch entry point is `./scripts/demo/start_model_analytics_dashboard.sh`; [Start the Dashboards](demo-guide.md#start-the-dashboards) supplies the procedure. Results are cached for five minutes and cannot alter the live cohort dashboard's vital-warning priorities.
