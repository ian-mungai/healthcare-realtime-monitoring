# Model Predictions

## Scope

The prediction datasets expose synthetic deterioration proxy scores for portfolio analytics. They are not clinically validated and must not be used for patient care.

## Score with a published model

Select an exact version-named model prefix rather than resolving a mutable `latest` pointer:

```zsh
export AWS_PROFILE="${AWS_PROFILE:-healthcare_realtime}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export DATA_BUCKET_NAME="$(terraform -chdir=infra output -raw raw_s3_bucket_name)"
export MODEL_VERSION="<reviewed-model-version>"

.venv/bin/python -m jobs.ml.score_logistic_regression \
  --model-s3-uri "s3://${DATA_BUCKET_NAME}/ml/model_artifacts/${MODEL_VERSION}" \
  --publish-s3
```

The scorer verifies the model and manifest SHA-256 metadata, checks the feature order, requires an evaluated threshold, scores without retraining, and writes the selected model-version partition idempotently.

## Athena presentation

- `healthcare_realtime_dbt.ml_predictions_serving` retains versioned scoring history.
- `healthcare_realtime_dbt.ml_predictions_latest` presents the most recent scoring run for reporting.
- `proxy_risk_band` uses `baseline_proxy` and `elevated_proxy`; it does not represent a diagnosis.
- `prediction_scope` and `is_clinically_validated` prevent the analytical output from being presented as a clinical system.

After publishing predictions, run dbt and Soda before connecting a reporting tool. Power BI report construction remains a separate portfolio step.
