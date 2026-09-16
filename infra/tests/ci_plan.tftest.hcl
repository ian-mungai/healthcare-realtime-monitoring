mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["example-region-1a", "example-region-1b"]
    }
  }

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "111111111111"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_region" {
    defaults = {
      region = "example-region-1"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

mock_provider "awscc" {}

variables {
  project_name                            = "example_project"
  deployment_environment                  = "test"
  kinesis_stream_name                     = "example_vitals"
  load_test_kinesis_stream_name           = "example_vitals_load_test"
  firehose_delivery_stream_name           = "example_firehose"
  glue_job_name                           = "example_raw_to_processed"
  raw_prefix                              = "raw/example/"
  airflow_pipeline_schedule               = "0 2 * * *"
  athena_workgroup_name                   = "example_workgroup"
  athena_results_s3_uri                   = "s3://ci-project-data-bucket/athena-results/"
  source_database_name                    = "example_source"
  processed_observations_table_name       = "example_processed"
  quarantine_table_name                   = "example_quarantine"
  dbt_database_name                       = "example_dbt"
  ml_database_name                        = "example_ml"
  ml_predictions_published_table_name     = "example_predictions_published"
  athena_catalog_name                     = "example_catalog"
  soda_data_source_name                   = "example_soda"
  dbt_staging_table_name                  = "example_staging"
  dbt_dim_patient_table_name              = "example_dim_patient"
  dbt_dim_encounter_table_name            = "example_dim_encounter"
  dbt_dim_provider_table_name             = "example_dim_provider"
  dbt_dim_observation_type_table_name     = "example_dim_observation_type"
  dbt_dim_date_table_name                 = "example_dim_date"
  dbt_fact_observations_table_name        = "example_fact_observations"
  dbt_encounter_features_table_name       = "example_encounter_features"
  dbt_ml_training_table_name              = "example_ml_training"
  dbt_ml_scoring_table_name               = "example_ml_scoring"
  dbt_ml_predictions_serving_table_name   = "example_predictions_serving"
  dbt_ml_predictions_latest_table_name    = "example_predictions_latest"
  latest_vitals_table_name                = "example-latest-vitals"
  processed_observations_state_table_name = "example-processed-observations"
  load_test_results_table_name            = "example-load-test-results"
  websocket_connections_table_name        = "example-websocket-connections"
  api_stage_name                          = "test"
  fhir_webhook_secret_id                  = "example/fhir-webhook"
  github_deployment_environment           = "test"
}

run "plan" {
  command = plan

  variables {
    aws_region                 = "example-region-1"
    data_bucket_name           = "ci-project-data-bucket"
    mwaa_source_bucket_name    = "ci-project-mwaa-source-bucket"
    realtime_alert_email       = "alerts@example.com"
    vitals_simulator_image_tag = "sha-ci"
    dbt_image_tag              = "sha-ci"
    soda_image_tag             = "sha-ci"
    ml_approved_model_version  = "logistic-ci"
  }

  assert {
    condition = alltrue([
      filebase64sha256("${path.module}/../build/lambda/fhir_webhook.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/vitals_stream_processor.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/websocket_handler.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/vitals_api.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/vitals_replay.zip") != "",
    ])
    error_message = "Every Lambda deployment package must produce a source code hash."
  }

  assert {
    condition     = module.mwaa.task_failure_alarm_name == "healthcare-realtime-pipeline-task-failure"
    error_message = "MWAA Serverless task failures must be connected to an actionable CloudWatch alarm."
  }

  assert {
    condition     = module.mwaa.trigger_mode == "scheduled"
    error_message = "An approved model version must enable the daily MWAA Serverless schedule."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.openlineage_emission_failures.alarm_name == "healthcare-realtime-openlineage-emission-failures"
    error_message = "Client-side OpenLineage delivery failures must raise an actionable alarm."
  }

  assert {
    condition     = module.dbt_ecs.predictions_database_name == "example_ml"
    error_message = "Published model predictions must use a dedicated Terraform-managed Glue database."
  }

  assert {
    condition     = contains(module.dbt_ecs.task_environment_names, "ATHENA_CATALOG")
    error_message = "The dbt ECS task must receive the configured Athena catalog."
  }
}

run "bootstrap_plan" {
  command = plan

  variables {
    aws_region                 = "example-region-1"
    data_bucket_name           = "ci-project-data-bucket"
    mwaa_source_bucket_name    = "ci-project-mwaa-source-bucket"
    realtime_alert_email       = "alerts@example.com"
    vitals_simulator_image_tag = "sha-ci"
    dbt_image_tag              = "sha-ci"
    soda_image_tag             = "sha-ci"
    ml_approved_model_version  = ""
  }

  assert {
    condition     = module.mwaa.trigger_mode == "manual_only"
    error_message = "First-deployment bootstrap must not schedule scoring before a model is approved."
  }
}

run "github_oidc_plan" {
  command = plan

  variables {
    aws_region                 = "example-region-1"
    data_bucket_name           = "ci-project-data-bucket"
    mwaa_source_bucket_name    = "ci-project-mwaa-source-bucket"
    realtime_alert_email       = "alerts@example.com"
    vitals_simulator_image_tag = "sha-ci"
    dbt_image_tag              = "sha-ci"
    soda_image_tag             = "sha-ci"
    ml_approved_model_version  = "logistic-ci"

    enable_github_oidc         = true
    github_repository          = "example-owner/healthcare-realtime-monitoring"
    github_oidc_subject_prefix = "repo:example-owner@1234/healthcare-realtime-monitoring@5678"
    github_deployment_policy_arns = [
      "arn:aws:iam::111111111111:policy/healthcare_realtime_deployment"
    ]
  }

  assert {
    condition     = aws_iam_role.github_deployment[0].max_session_duration == 3600
    error_message = "GitHub OIDC deployment role must use bounded one-hour sessions."
  }
}

run "openlineage_collector_plan" {
  command = plan

  variables {
    aws_region                 = "example-region-1"
    data_bucket_name           = "ci-project-data-bucket"
    mwaa_source_bucket_name    = "ci-project-mwaa-source-bucket"
    realtime_alert_email       = "alerts@example.com"
    vitals_simulator_image_tag = "sha-ci"
    dbt_image_tag              = "sha-ci"
    soda_image_tag             = "sha-ci"
    ml_approved_model_version  = "logistic-ci"

    enable_openlineage_collector        = true
    openlineage_collector_image_tag     = "sha-ci"
    openlineage_collector_desired_count = 1
  }

  assert {
    condition     = module.openlineage_collector.image_tag_mutability == "IMMUTABLE"
    error_message = "The managed Marquez repository must reject mutable image tags."
  }

  assert {
    condition     = module.openlineage_collector.ingestion_authorization_type == "AWS_IAM"
    error_message = "The managed OpenLineage ingestion route must require AWS IAM authorization."
  }

  assert {
    condition     = !contains(module.openlineage_collector.route_keys, "$default")
    error_message = "The managed collector must expose explicit routes instead of a full-API default proxy."
  }

  assert {
    condition = (
      module.openlineage_collector.database_recovery.backup_retention_days >= 7 &&
      module.openlineage_collector.database_recovery.final_snapshot_required
    )
    error_message = "The managed collector database must retain seven days of backups and require a final snapshot."
  }

  assert {
    condition     = length(module.openlineage_collector.alarm_names) == 5
    error_message = "The running managed collector must expose five actionable health and delivery alarms."
  }
}
