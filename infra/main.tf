module "kinesis" {
  source = "./modules/kinesis"

  stream_name            = var.kinesis_stream_name
  retention_period_hours = 24
  stream_mode            = "ON_DEMAND"

  tags = local.common_tags
}

module "load_test_kinesis" {
  source = "./modules/kinesis"

  stream_name            = var.load_test_kinesis_stream_name
  retention_period_hours = 24
  stream_mode            = "ON_DEMAND"

  tags = merge(local.common_tags, {
    Purpose = "load-testing"
  })
}

module "raw_s3" {
  source = "./modules/raw_s3"

  bucket_name   = var.data_bucket_name
  force_destroy = var.allow_destructive_teardown

  tags = merge(local.common_tags, { Layer = "raw" })
}

module "openlineage_collector" {
  source = "./modules/openlineage_collector"

  depends_on = [aws_api_gateway_account.cloudwatch]

  enabled                    = var.enable_openlineage_collector
  vpc_id                     = module.network.vpc_id
  private_subnet_ids         = module.network.private_subnet_ids
  ecs_cluster_arn            = module.hapi_ecs.cluster_arn
  image_tag                  = var.openlineage_collector_image_tag
  desired_count              = var.openlineage_collector_desired_count
  allow_destructive_teardown = var.allow_destructive_teardown
  skip_final_snapshot        = var.openlineage_skip_final_snapshot
  final_snapshot_identifier  = var.openlineage_final_snapshot_identifier
  stage_name                 = var.api_stage_name
  alarm_topic_arn            = module.realtime_observability.alert_topic_arn

  tags = local.common_tags
}

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.deployment_environment
    ManagedBy   = "terraform"
  }
  effective_openlineage_collector_url = var.enable_openlineage_collector ? module.openlineage_collector.collector_url : var.external_openlineage_collector_url
  openlineage_collector_invoke_arn    = var.enable_openlineage_collector ? module.openlineage_collector.invoke_arn : ""
}

module "firehose" {
  source = "./modules/firehose"

  delivery_stream_name = var.firehose_delivery_stream_name
  kinesis_stream_arn   = module.kinesis.stream_arn
  s3_bucket_arn        = module.raw_s3.bucket_arn

  tags = local.common_tags
}

module "glue" {
  source = "./modules/glue"

  bucket_name                      = module.raw_s3.bucket_name
  project_name                     = var.project_name
  database_name                    = var.source_database_name
  processed_table_name             = var.processed_observations_table_name
  quarantine_table_name            = var.quarantine_table_name
  job_name                         = var.glue_job_name
  script_key                       = "scripts/glue/fhir_observations_raw_to_processed.py"
  quarantine_path                  = "s3://${module.raw_s3.bucket_name}/quarantine/fhir_observations/"
  metrics_path                     = "s3://${module.raw_s3.bucket_name}/metrics/glue/"
  openlineage_collector_url        = local.effective_openlineage_collector_url
  openlineage_collector_invoke_arn = local.openlineage_collector_invoke_arn

  tags = local.common_tags

  depends_on = [
    module.raw_s3,
  ]
}

module "network" {
  source = "./modules/network"

  name = "healthcare_realtime_mwaa"

  tags = local.common_tags
}

module "mwaa" {
  source = "./modules/mwaa"

  workflow_name    = "healthcare_realtime_pipeline"
  data_bucket_name = module.raw_s3.bucket_name
  enable_schedule  = var.ml_approved_model_version != ""

  dbt_ecs_task_definition_family  = module.dbt_ecs.task_definition_family
  dbt_ecs_task_role_arn           = module.dbt_ecs.task_role_arn
  dbt_ecs_task_execution_role_arn = module.dbt_ecs.task_execution_role_arn

  soda_ecs_task_definition_family  = module.soda_ecs.task_definition_family
  soda_ecs_task_role_arn           = module.soda_ecs.task_role_arn
  soda_ecs_task_execution_role_arn = module.soda_ecs.task_execution_role_arn

  glue_job_name      = module.glue.job_name
  glue_database_name = module.glue.database_name

  openlineage_collector_invoke_arn = local.openlineage_collector_invoke_arn
  alarm_topic_arn                  = module.realtime_observability.alert_topic_arn

  subnet_ids = module.network.private_subnet_ids

  security_group_ids = [
    module.network.security_group_id
  ]

  tags = local.common_tags

  depends_on = [module.raw_s3]
}

module "observability" {
  source = "./modules/observability"

  aws_region = var.aws_region

  kinesis_stream_name           = module.kinesis.stream_name
  firehose_delivery_stream_name = module.firehose.delivery_stream_name
  glue_job_name                 = module.glue.job_name

  ecs_cluster_name            = module.dbt_ecs.cluster_name
  dbt_task_definition_family  = module.dbt_ecs.task_definition_family
  soda_task_definition_family = module.soda_ecs.task_definition_family
  alarm_topic_arn             = module.realtime_observability.alert_topic_arn

  tags = local.common_tags
}

module "dbt_ecs" {
  source = "./modules/dbt_ecs"

  vpc_id                           = module.network.vpc_id
  private_subnet_ids               = module.network.private_subnet_ids
  data_bucket_name                 = module.raw_s3.bucket_name
  image_tag                        = var.dbt_image_tag
  force_delete_repository          = var.allow_destructive_teardown
  approved_model_version           = var.ml_approved_model_version
  openlineage_collector_url        = local.effective_openlineage_collector_url
  openlineage_collector_invoke_arn = local.openlineage_collector_invoke_arn

  source_database_name                = var.source_database_name
  dbt_database_name                   = var.dbt_database_name
  ml_database_name                    = var.ml_database_name
  ml_predictions_published_table_name = var.ml_predictions_published_table_name
  data_identifiers = {
    PROJECT_NAME                       = var.project_name
    ATHENA_CATALOG                     = var.athena_catalog_name
    ATHENA_SOURCE_DATABASE             = var.source_database_name
    ATHENA_DBT_DATABASE                = var.dbt_database_name
    ATHENA_ML_DATABASE                 = var.ml_database_name
    ATHENA_PROCESSED_TABLE             = var.processed_observations_table_name
    ATHENA_PREDICTIONS_PUBLISHED_TABLE = var.ml_predictions_published_table_name
    ATHENA_RESULTS_S3_URI              = var.athena_results_s3_uri
    DBT_STAGING_TABLE                  = var.dbt_staging_table_name
    DBT_DIM_PATIENT_TABLE              = var.dbt_dim_patient_table_name
    DBT_DIM_ENCOUNTER_TABLE            = var.dbt_dim_encounter_table_name
    DBT_DIM_PROVIDER_TABLE             = var.dbt_dim_provider_table_name
    DBT_DIM_OBSERVATION_TYPE_TABLE     = var.dbt_dim_observation_type_table_name
    DBT_DIM_DATE_TABLE                 = var.dbt_dim_date_table_name
    DBT_FACT_OBSERVATIONS_TABLE        = var.dbt_fact_observations_table_name
    DBT_ENCOUNTER_FEATURES_TABLE       = var.dbt_encounter_features_table_name
    ACTIVE_PATIENT_IDS                 = join(",", var.active_patient_ids)
    DBT_ML_TRAINING_TABLE              = var.dbt_ml_training_table_name
    DBT_ML_SCORING_TABLE               = var.dbt_ml_scoring_table_name
    DBT_ML_PREDICTIONS_SERVING_TABLE   = var.dbt_ml_predictions_serving_table_name
    DBT_ML_PREDICTIONS_LATEST_TABLE    = var.dbt_ml_predictions_latest_table_name
  }

  tags = local.common_tags
}

module "soda_ecs" {
  source = "./modules/soda_ecs"

  vpc_id                           = module.network.vpc_id
  private_subnet_ids               = module.network.private_subnet_ids
  data_bucket_name                 = module.raw_s3.bucket_name
  image_tag                        = var.soda_image_tag
  force_delete_repository          = var.allow_destructive_teardown
  openlineage_collector_url        = local.effective_openlineage_collector_url
  openlineage_collector_invoke_arn = local.openlineage_collector_invoke_arn

  source_database_name = var.source_database_name
  dbt_database_name    = var.dbt_database_name
  ml_database_name     = var.ml_database_name
  data_identifiers = {
    PROJECT_NAME                     = var.project_name
    SODA_DATA_SOURCE_NAME            = var.soda_data_source_name
    ATHENA_CATALOG                   = var.athena_catalog_name
    ATHENA_SOURCE_DATABASE           = var.source_database_name
    ATHENA_DBT_DATABASE              = var.dbt_database_name
    ATHENA_ML_DATABASE               = var.ml_database_name
    ATHENA_PROCESSED_TABLE           = var.processed_observations_table_name
    ATHENA_RESULTS_S3_URI            = var.athena_results_s3_uri
    DBT_STAGING_TABLE                = var.dbt_staging_table_name
    DBT_DIM_PATIENT_TABLE            = var.dbt_dim_patient_table_name
    DBT_DIM_ENCOUNTER_TABLE          = var.dbt_dim_encounter_table_name
    DBT_DIM_PROVIDER_TABLE           = var.dbt_dim_provider_table_name
    DBT_DIM_OBSERVATION_TYPE_TABLE   = var.dbt_dim_observation_type_table_name
    DBT_DIM_DATE_TABLE               = var.dbt_dim_date_table_name
    DBT_FACT_OBSERVATIONS_TABLE      = var.dbt_fact_observations_table_name
    DBT_ENCOUNTER_FEATURES_TABLE     = var.dbt_encounter_features_table_name
    DBT_ML_TRAINING_TABLE            = var.dbt_ml_training_table_name
    DBT_ML_PREDICTIONS_SERVING_TABLE = var.dbt_ml_predictions_serving_table_name
    DBT_ML_PREDICTIONS_LATEST_TABLE  = var.dbt_ml_predictions_latest_table_name
  }

  tags = local.common_tags
}

module "vitals_simulator_ecs" {
  source = "./modules/vitals_simulator_ecs"

  aws_region = var.aws_region

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids

  ecs_cluster_arn = module.hapi_ecs.cluster_arn
  fhir_base_url   = module.hapi_ecs.fhir_base_url

  data_bucket_name        = module.raw_s3.bucket_name
  image_tag               = var.vitals_simulator_image_tag
  force_delete_repository = var.allow_destructive_teardown
  alarm_topic_arn         = module.realtime_observability.alert_topic_arn

  tags = local.common_tags
}

module "realtime_vitals" {
  source = "./modules/realtime_vitals"

  deletion_protection_enabled       = !var.allow_destructive_teardown
  latest_vitals_table_name          = var.latest_vitals_table_name
  processed_observations_table_name = var.processed_observations_state_table_name
  load_test_results_table_name      = var.load_test_results_table_name
  websocket_connections_table_name  = var.websocket_connections_table_name

  tags = local.common_tags
}

module "realtime_processor" {
  source = "./modules/realtime_processor"

  aws_region = var.aws_region

  kinesis_stream_arn       = module.kinesis.stream_arn
  load_test_stream_arn     = module.load_test_kinesis.stream_arn
  latest_vitals_table_name = module.realtime_vitals.latest_vitals_table_name
  latest_vitals_table_arn  = module.realtime_vitals.latest_vitals_table_arn
  idempotency_table_name   = module.realtime_vitals.processed_observations_table_name
  idempotency_table_arn    = module.realtime_vitals.processed_observations_table_arn
  load_test_table_name     = module.realtime_vitals.load_test_results_table_name
  load_test_table_arn      = module.realtime_vitals.load_test_results_table_arn
  lambda_zip_path          = "${path.root}/../build/lambda/vitals_stream_processor.zip"
  connections_table_name   = module.realtime_vitals.websocket_connections_table_name
  connections_table_arn    = module.realtime_vitals.websocket_connections_table_arn
  websocket_api_id         = module.realtime_websocket.api_id
  websocket_stage_name     = var.api_stage_name
  failure_queue_arn        = module.realtime_failure_handling.vitals_failures_queue_arn

  tags = local.common_tags
}

module "realtime_websocket" {
  source = "./modules/realtime_websocket"

  depends_on = [aws_api_gateway_account.cloudwatch]

  aws_region = var.aws_region

  connections_table_name = module.realtime_vitals.websocket_connections_table_name
  connections_table_arn  = module.realtime_vitals.websocket_connections_table_arn
  lambda_zip_path        = "${path.root}/../build/lambda/websocket_handler.zip"
  patient_access_policy  = jsonencode(var.realtime_patient_access_policy)
  stage_name             = var.api_stage_name

  tags = local.common_tags
}

module "vitals_api" {
  source = "./modules/vitals_api"

  depends_on = [aws_api_gateway_account.cloudwatch]

  aws_region = var.aws_region

  latest_vitals_table_name = module.realtime_vitals.latest_vitals_table_name
  latest_vitals_table_arn  = module.realtime_vitals.latest_vitals_table_arn

  lambda_zip_path       = "${path.root}/../build/lambda/vitals_api.zip"
  patient_access_policy = jsonencode(var.realtime_patient_access_policy)
  stage_name            = var.api_stage_name

  tags = local.common_tags
}

module "realtime_observability" {
  source = "./modules/realtime_observability"

  aws_region = var.aws_region

  lambda_function_name = module.realtime_processor.lambda_function_name
  environment          = var.deployment_environment
  alert_email          = var.realtime_alert_email
  replay_dlq_name      = module.realtime_failure_handling.vitals_replay_dlq_name

  tags = local.common_tags
}

module "realtime_failure_handling" {
  source = "./modules/realtime_failure_handling"

  environment = var.deployment_environment

  tags = local.common_tags
}

module "realtime_replay" {
  source = "./modules/realtime_replay"

  aws_region = var.aws_region

  kinesis_stream_arn = module.kinesis.stream_arn
  failure_queue_arn  = module.realtime_failure_handling.vitals_failures_queue_arn
  replay_dlq_arn     = module.realtime_failure_handling.vitals_replay_dlq_arn
  replay_dlq_url     = module.realtime_failure_handling.vitals_replay_dlq_url
  lambda_zip_path    = "${path.root}/../build/lambda/vitals_replay.zip"

  tags = local.common_tags
}

module "hapi_ecs" {
  source = "./modules/hapi_ecs"

  vpc_id              = module.network.vpc_id
  public_subnet_ids   = module.network.public_subnet_ids
  private_subnet_ids  = module.network.private_subnet_ids
  deletion_protection = !var.allow_destructive_teardown
  skip_final_snapshot = var.hapi_skip_final_snapshot

  tags = local.common_tags
}
