---
title: "Model Training"
description: "Build and evaluate a patient-grouped synthetic proxy baseline with reproducible artifacts."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Model Training

For developers and operators: build and evaluate a patient-grouped synthetic proxy baseline with reproducible artifacts.

## Contents

- [Terminology](#terminology)
- [Example Placeholders](#example-placeholders)
- [Before You Start](#before-you-start)
- [Scope](#scope)
- [Dataset Contract](#dataset-contract)
- [Train Locally From Athena](#train-locally-from-athena)
- [Activate a Reviewed Model](#activate-a-reviewed-model)

## Terminology

- **AUC**: area under the curve.
- **AWS**: Amazon Web Services.
- **BIDMC**: Beth Israel Deaconess Medical Center.
- **DAG**: directed acyclic graph.
- **MWAA**: Managed Workflows for Apache Airflow.
- **ROC**: receiver operating characteristic.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<MODEL_VERSION>`: model version for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or AWS commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## Scope

The baseline estimates the synthetic deterioration proxy from encounter-level vital aggregates. It demonstrates reproducible feature consumption and model packaging; it is not clinically validated and must not be used for patient care.

## Dataset Contract

`${ATHENA_DBT_DATABASE}.${DBT_ML_TRAINING_TABLE}` contains one row per eligible encounter. Features come from the first fixed 15 minutes and the proxy label comes from the following fixed 15 minutes; short encounters without both windows are excluded. The versioned proxy requires repeated extreme observations of the same vital so that an isolated synthetic measurement cannot determine the label. It carries twelve numeric features, a binary proxy label, versioned feature and label definitions and a deterministic patient-grouped split. Patient and provider identifiers are not model features.

The committed dbt tests require both partitions, reject patient leakage and warn when either partition lacks both label classes. The training command treats the missing-class warning as a hard failure. Soda validates population, key completeness, split values and label values.

Each simulator task creates a fresh encounter for every patient and assigns either a `normal` or `deterioration_proxy` scenario. For runs planned to cover the full 30-minute window, selection favors each patient's less frequent scenario among tagged encounters in HAPI FHIR. Ties use `SIMULATOR_SCENARIO_SEED` and the patient identifier or a random choice. Shorter planned runs use the seed or random choice without reading or adding history tags; the same seed reproduces ties and no-history choices, not every history-based assignment.

The first 15 minutes preserve the source Beth Israel Deaconess Medical Center (BIDMC) readings and Synthea blood pressure. During the following 15 minutes, the normal scenario constrains measurements below the proxy thresholds while the deterioration scenario emits repeated synthetic threshold crossings. Start with two complete 30-minute simulations and rerun the analytical workflow, then inspect actual window and class-readiness results. Tags record assignments at startup, so retained history, interruptions or concurrent runs prevent a universal two-run guarantee. Training still requires observations in both windows, both classes in both patient-grouped partitions and no patient leakage. Repeat or diagnose a failed readiness check before training; do not bypass it. The [star-schema reference](analytics-star-schema.md#feature-and-label-construction) defines planned eligibility, history and the preserved prior assignment rule.

## Train Locally From Athena

Use the project virtual environment and deployment-specific bucket output without placing that value in documentation:

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
   export DBT_ML_TRAINING_TABLE="$(jq -r '.dbt_ml_training_table_name' infra/deployment.auto.tfvars.json)"

   .venv/bin/python -m jobs.ml.train_logistic_regression \
     --predictions-database "$ATHENA_ML_DATABASE" \
     --predictions-table "$ATHENA_PREDICTIONS_PUBLISHED_TABLE" \
     --publish-s3
   ```

   The ignored `build/ml/logistic_baseline/` directory receives:

   - `model.joblib`, containing median imputation, standardization and class-balanced logistic regression;
   - `manifest.json`, containing the model version, dataset fingerprint, feature order, schema versions, split strategy, row counts, random seed and evaluation summary;
   - `evaluation.json`, containing test-set receiver operating characteristic (ROC) area under the curve (AUC), sensitivity, specificity, balanced accuracy and confusion-matrix counts at the default and selected operating points.
   - `predictions.jsonl`, containing encounter-level probabilities and classifications for reproducibility.

   With `--publish-s3`, the command uploads checksummed copies to the existing encrypted, versioned project bucket. Model artifacts use `ml/model_artifacts/<MODEL_VERSION>/`; predictions use a model-version partition under `ml/predictions/`. It registers only that partition in the Terraform-owned `${ATHENA_ML_DATABASE}.${ATHENA_PREDICTIONS_PUBLISHED_TABLE}` table. No ad hoc process creates objects in dbt's catalog.

   The next dbt build materializes `${ATHENA_DBT_DATABASE}.${DBT_ML_PREDICTIONS_SERVING_TABLE}`. dbt and Soda validate its `(model_version, encounter_key)` grain, probability and threshold ranges, binary predictions, required metadata and source-row relationships.

   The default operating point uses a `0.5` decision threshold. An exploratory alternative maximizes Youden's J statistic on the training partition and is then measured on the untouched test partition. Selecting a production threshold requires an independent validation cohort and clinical review; these synthetic proxy-label results are portfolio evidence, not a clinical performance claim.

   Training and evaluation stop with a clear error when either partition cannot support binary classification.

2. Inspect the manifest and evaluation artifacts. Confirm both patient-grouped partitions contain both label classes, the feature schema is `vital-features-v2` and the published checksums match the local artifacts. Successful training produces all four files and the model-version partition without validation errors.

## Activate a Reviewed Model

Prerequisites:

- A reviewed immutable model version with matching artifact checksums and feature schema `vital-features-v2`.
- The selected environment's deployed backend and private configuration.
- Owner approval for the exact deployment plan before applying it.

1. Set the reviewed version in the selected `${PROJECT_ENV_FILE:-.env}` file:

   ```dotenv
   ML_APPROVED_MODEL_VERSION=<MODEL_VERSION>
   ```

2. Render the ignored Terraform inputs. Do not edit generated inputs directly:

   ```zsh
   ./scripts/infrastructure/render_project_config.sh
   ```

3. Create and inspect a saved plan:

   ```zsh
   terraform -chdir=infra plan -var-file=deployment.auto.tfvars.json -out=tfplan-model
   terraform -chdir=infra show -no-color tfplan-model
   ```

4. Obtain approval for that plan's exact changes. Stop on unexpected deletion, replacement or permission changes.
5. Apply only the reviewed and approved plan:

   ```zsh
   terraform -chdir=infra apply tfplan-model
   ```

6. Run the analytical workflow and verify that scoring uses the approved version. Confirm the serving predictions pass dbt and Soda checks and the daily Managed Workflows for Apache Airflow (MWAA) schedule is enabled.

An empty approved version is permitted only during first-deployment bootstrap and keeps MWAA in manual-only mode. The scorer rejects a model trained against an older feature schema. Training is outside the daily directed acyclic graph (DAG).
