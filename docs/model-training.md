# Model Training

## Scope

The baseline estimates the synthetic deterioration proxy from encounter-level vital aggregates. It demonstrates reproducible feature consumption and model packaging; it is not clinically validated and must not be used for patient care.

## Dataset contract

`healthcare_realtime_dbt.ml_training_dataset` contains one row per eligible encounter. It carries twelve numeric features, a binary proxy label, versioned feature and label definitions, and a deterministic patient-grouped split. Patient and provider identifiers are not model features.

The committed dbt tests require both train and test partitions and reject patient leakage between them. Soda validates population, key completeness, split values, and label values.

## Train locally from Athena

Use the project virtual environment and deployment-specific bucket output without placing that value in documentation:

```zsh
export AWS_PROFILE="${AWS_PROFILE:-healthcare_realtime}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DATA_BUCKET_NAME="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"

.venv/bin/python -m jobs.ml.train_logistic_regression
```

The ignored `build/ml/logistic_baseline/` directory receives:

- `model.joblib`, containing median imputation, standardization, and class-balanced logistic regression;
- `manifest.json`, containing the model version, dataset fingerprint, feature order, schema versions, split strategy, row counts, random seed, and evaluation summary;
- `evaluation.json`, containing test-set ROC AUC, sensitivity, specificity, balanced accuracy, and confusion-matrix counts at the default and selected operating points.

The default operating point uses a `0.5` decision threshold. An exploratory alternative maximizes Youden's J statistic on the training partition and is then measured on the untouched test partition. Selecting a production threshold requires an independent validation cohort and clinical review; these synthetic proxy-label results are portfolio evidence, not a clinical performance claim.

Training and evaluation stop with a clear error when either partition cannot support binary classification. Model deployment approval remains a separate controlled step.
