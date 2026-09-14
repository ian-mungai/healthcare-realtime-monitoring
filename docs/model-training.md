# Model Training

## Scope

The baseline estimates the synthetic deterioration proxy from encounter-level vital aggregates. It demonstrates reproducible feature consumption and model packaging; it is not clinically validated and must not be used for patient care.

## Dataset contract

`healthcare_realtime_dbt.ml_training_dataset` contains one row per eligible encounter. Features come from the first fixed 15 minutes and the proxy label comes from the following fixed 15 minutes; short encounters without both windows are excluded. It carries twelve numeric features, a binary proxy label, versioned feature and label definitions, and a deterministic patient-grouped split. Patient and provider identifiers are not model features.

The committed dbt tests require both train and test partitions and reject patient leakage between them. Soda validates population, key completeness, split values, and label values.

## Train locally from Athena

Use the project virtual environment and deployment-specific bucket output without placing that value in documentation:

```zsh
export AWS_PROFILE="${AWS_PROFILE:-healthcare_realtime}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DATA_BUCKET_NAME="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"

.venv/bin/python -m jobs.ml.train_logistic_regression \
  --predictions-database healthcare_realtime_ml \
  --publish-s3
```

The ignored `build/ml/logistic_baseline/` directory receives:

- `model.joblib`, containing median imputation, standardization, and class-balanced logistic regression;
- `manifest.json`, containing the model version, dataset fingerprint, feature order, schema versions, split strategy, row counts, random seed, and evaluation summary;
- `evaluation.json`, containing test-set ROC AUC, sensitivity, specificity, balanced accuracy, and confusion-matrix counts at the default and selected operating points.
- `predictions.jsonl`, containing encounter-level probabilities and classifications for reproducibility.

With `--publish-s3`, the command uploads checksummed copies to the existing encrypted, versioned project bucket. Model artifacts use `ml/model_artifacts/<model-version>/`; predictions use a model-version partition under `ml/predictions/`. It registers only that partition in the Terraform-owned `healthcare_realtime_ml.ml_predictions_published` table. No ad hoc process creates objects in dbt's catalog.

The next dbt build materializes `healthcare_realtime_dbt.ml_predictions_serving`. dbt and Soda validate its `(model_version, encounter_key)` grain, probability and threshold ranges, binary predictions, required metadata, and source-row relationships.

The default operating point uses a `0.5` decision threshold. An exploratory alternative maximizes Youden's J statistic on the training partition and is then measured on the untouched test partition. Selecting a production threshold requires an independent validation cohort and clinical review; these synthetic proxy-label results are portfolio evidence, not a clinical performance claim.

Training and evaluation stop with a clear error when either partition cannot support binary classification. Model deployment approval remains a separate controlled step: copy the reviewed immutable version into `ml_approved_model_version` in the ignored Terraform inputs, create and inspect a saved plan, and apply that exact plan. An empty version is permitted only during first-deployment bootstrap and keeps MWAA in manual-only mode; setting the reviewed version enables the daily schedule. The fixed-window change is feature schema `vital-features-v2`; the scorer rejects a model trained against an older feature schema. Training is not part of the daily DAG.
