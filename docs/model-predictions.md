# Model Predictions

## Scope

The prediction datasets expose synthetic deterioration proxy scores for portfolio analytics. They are not clinically validated and must not be used for patient care.

## Score with a published model

Select an exact version-named model prefix rather than resolving a mutable `latest` pointer:

```zsh
export AWS_PROFILE="${AWS_PROFILE:-healthcare_realtime}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DATA_BUCKET_NAME="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"
export ML_APPROVED_MODEL_VERSION="<reviewed-model-version>"

.venv/bin/python -m jobs.ml.score_logistic_regression \
  --model-s3-uri "s3://${DATA_BUCKET_NAME}/ml/model_artifacts/${ML_APPROVED_MODEL_VERSION}" \
  --predictions-database healthcare_realtime_ml \
  --publish-s3
```

The scorer verifies the model and manifest SHA-256 metadata, checks the feature order, requires an evaluated threshold, scores without retraining, and writes the selected model-version partition idempotently.

## Athena presentation

- `healthcare_realtime_dbt.ml_predictions_serving` retains versioned scoring history.
- `healthcare_realtime_dbt.ml_predictions_latest` presents only the Terraform-configured approved model version for reporting.
- `proxy_risk_band` uses `baseline_proxy` and `elevated_proxy`; it does not represent a diagnosis.
- `prediction_scope` and `is_clinically_validated` prevent the analytical output from being presented as a clinical system.

## Daily orchestration

The native Airflow DAG and generated MWAA Serverless workflow run this sequence each day at `02:00` UTC:

```text
dbt feature build -> approved-model scoring -> prediction-view refresh -> Soda freshness and contract checks
```

The scorer reads `healthcare_realtime_dbt.ml_scoring_dataset`, which does not require a completed outcome window or training label. It resolves the exact artifact from `ML_APPROVED_MODEL_VERSION`, never a mutable `latest` pointer, and does not retrain. Soda fails the workflow when the newest `scored_at` is 26 hours old or older.

The Streamlit dashboard's separate **Model analytics** mode reads `ml_predictions_latest` through Athena and shows one latest prediction per patient. Results are cached for five minutes and cannot alter the live cohort's vital-warning priorities.
