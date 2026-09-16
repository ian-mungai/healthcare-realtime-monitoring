import os

TEST_ENVIRONMENT = {
    "AWS_REGION": "example-region-1",
    "AWS_DEFAULT_REGION": "example-region-1",
    "PROJECT_NAME": "example-project",
    "DATA_BUCKET_NAME": "example-data-bucket",
    "GLUE_JOB_NAME": "example-glue-job",
    "KINESIS_STREAM_NAME": "example-vitals",
    "LOAD_TEST_KINESIS_STREAM_NAME": "example-vitals-load-test",
    "LATEST_VITALS_TABLE": "example-latest-vitals",
    "LOAD_TEST_RESULTS_TABLE": "example-load-test-results",
    "CONNECTIONS_TABLE": "example-websocket-connections",
    "IDEMPOTENCY_TABLE": "example-processed-observations",
    "ATHENA_SOURCE_DATABASE": "example_source",
    "ATHENA_DBT_DATABASE": "example_dbt",
    "ATHENA_ML_DATABASE": "example_ml",
    "ATHENA_PROCESSED_TABLE": "example_processed_observations",
    "ATHENA_PREDICTIONS_PUBLISHED_TABLE": "example_predictions_published",
    "DBT_STAGING_TABLE": "example_staging",
    "DBT_DIM_PATIENT_TABLE": "example_dim_patient",
    "DBT_DIM_ENCOUNTER_TABLE": "example_dim_encounter",
    "DBT_DIM_PROVIDER_TABLE": "example_dim_provider",
    "DBT_DIM_OBSERVATION_TYPE_TABLE": "example_dim_observation_type",
    "DBT_DIM_DATE_TABLE": "example_dim_date",
    "DBT_FACT_OBSERVATIONS_TABLE": "example_fact_observations",
    "DBT_ENCOUNTER_FEATURES_TABLE": "example_encounter_features",
    "DBT_ML_TRAINING_TABLE": "example_ml_training",
}

for name, value in TEST_ENVIRONMENT.items():
    os.environ.setdefault(name, value)
