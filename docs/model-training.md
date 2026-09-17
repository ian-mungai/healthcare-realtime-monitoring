# Model Training

## Scope

The baseline estimates the synthetic deterioration proxy from encounter-level vital aggregates. It demonstrates reproducible feature consumption and model packaging; it is not clinically validated and must not be used for patient care.

## Dataset contract

`${ATHENA_DBT_DATABASE}.${DBT_ML_TRAINING_TABLE}` contains one row per eligible encounter. Features come from the first fixed 15 minutes and the proxy label comes from the following fixed 15 minutes; short encounters without both windows are excluded. The versioned proxy requires repeated extreme observations of the same vital so that an isolated synthetic measurement cannot determine the label. It carries twelve numeric features, a binary proxy label, versioned feature and label definitions and a deterministic patient-grouped split. Patient and provider identifiers are not model features.

The committed dbt tests require both partitions, reject patient leakage and warn when either partition lacks both label classes. The training command treats the missing-class warning as a hard failure. Soda validates population, key completeness, split values and label values.

Each simulator task creates a fresh encounter for every patient and randomly assigns either a `normal` or `deterioration_proxy` scenario to that encounter. The first 15 minutes preserve the source BIDMC readings. During the following 15 minutes, the normal scenario constrains measurements below the proxy thresholds while the deterioration scenario emits repeated synthetic threshold crossings. Scenario choices are independent for each patient and each task, so one run does not guarantee both classes in both patient-grouped partitions. Run multiple complete 30-minute simulations and rerun the analytical workflow until the readiness tests confirm both classes without patient leakage.

## Train locally from Athena

Use the project virtual environment and deployment-specific bucket output without placing that value in documentation:

```zsh
set -a
source .env
set +a
export DATA_BUCKET_NAME="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"

.venv/bin/python -m jobs.ml.train_logistic_regression \
  --predictions-database "$ATHENA_ML_DATABASE" \
  --predictions-table "$ATHENA_PREDICTIONS_PUBLISHED_TABLE" \
  --publish-s3
```

The ignored `build/ml/logistic_baseline/` directory receives:

- `model.joblib`, containing median imputation, standardization and class-balanced logistic regression;
- `manifest.json`, containing the model version, dataset fingerprint, feature order, schema versions, split strategy, row counts, random seed and evaluation summary;
- `evaluation.json`, containing test-set ROC AUC, sensitivity, specificity, balanced accuracy and confusion-matrix counts at the default and selected operating points.
- `predictions.jsonl`, containing encounter-level probabilities and classifications for reproducibility.

With `--publish-s3`, the command uploads checksummed copies to the existing encrypted, versioned project bucket. Model artifacts use `ml/model_artifacts/<model-version>/`; predictions use a model-version partition under `ml/predictions/`. It registers only that partition in the Terraform-owned `${ATHENA_ML_DATABASE}.${ATHENA_PREDICTIONS_PUBLISHED_TABLE}` table. No ad hoc process creates objects in dbt's catalog.

The next dbt build materializes `${ATHENA_DBT_DATABASE}.${DBT_ML_PREDICTIONS_SERVING_TABLE}`. dbt and Soda validate its `(model_version, encounter_key)` grain, probability and threshold ranges, binary predictions, required metadata and source-row relationships.

The default operating point uses a `0.5` decision threshold. An exploratory alternative maximizes Youden's J statistic on the training partition and is then measured on the untouched test partition. Selecting a production threshold requires an independent validation cohort and clinical review; these synthetic proxy-label results are portfolio evidence, not a clinical performance claim.

Training and evaluation stop with a clear error when either partition cannot support binary classification. Model deployment approval remains a separate controlled step: copy the reviewed immutable version into `ml_approved_model_version` in the ignored Terraform inputs, create and inspect a saved plan and apply that exact plan. An empty version is permitted only during first-deployment bootstrap and keeps MWAA in manual-only mode; setting the reviewed version enables the daily schedule. The fixed-window change is feature schema `vital-features-v2`; the scorer rejects a model trained against an older feature schema. Training is not part of the daily DAG.
