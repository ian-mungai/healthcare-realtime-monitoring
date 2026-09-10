module "kinesis" {
  source = "./modules/kinesis"

  stream_name            = "healthcare_realtime_vitals"
  retention_period_hours = 24
  stream_mode            = "ON_DEMAND"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "load_test_kinesis" {
  source = "./modules/kinesis"

  stream_name            = "healthcare_realtime_vitals_load_test"
  retention_period_hours = 24
  stream_mode            = "ON_DEMAND"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
    Purpose     = "load-testing"
  }
}

module "raw_s3" {
  source = "./modules/raw_s3"

  bucket_name = var.data_bucket_name

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    Layer       = "raw"
    ManagedBy   = "terraform"
  }
}

module "firehose" {
  source = "./modules/firehose"

  delivery_stream_name = "healthcare_realtime_firehose"
  kinesis_stream_arn   = module.kinesis.stream_arn
  s3_bucket_arn        = module.raw_s3.bucket_arn

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "glue" {
  source = "./modules/glue"

  bucket_name               = module.raw_s3.bucket_name
  database_name             = "healthcare_realtime"
  job_name                  = "healthcare_realtime_raw_to_processed"
  script_key                = "scripts/glue/fhir_observations_raw_to_processed.py"
  quarantine_path           = "s3://${module.raw_s3.bucket_name}/quarantine/fhir_observations/"
  metrics_path              = "s3://${module.raw_s3.bucket_name}/metrics/glue/"
  openlineage_collector_url = var.openlineage_collector_url

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }

  depends_on = [
    module.raw_s3,
  ]
}

module "network" {
  source = "./modules/network"

  name = "healthcare_realtime_mwaa"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "mwaa" {
  source = "./modules/mwaa"

  workflow_name      = "healthcare_realtime_pipeline"
  source_bucket_name = var.mwaa_source_bucket_name
  data_bucket_name   = module.raw_s3.bucket_name

  dbt_ecs_task_definition_family  = module.dbt_ecs.task_definition_family
  dbt_ecs_task_role_arn           = module.dbt_ecs.task_role_arn
  dbt_ecs_task_execution_role_arn = module.dbt_ecs.task_execution_role_arn

  soda_ecs_task_definition_family  = module.soda_ecs.task_definition_family
  soda_ecs_task_role_arn           = module.soda_ecs.task_role_arn
  soda_ecs_task_execution_role_arn = module.soda_ecs.task_execution_role_arn

  glue_job_name      = module.glue.job_name
  glue_database_name = module.glue.database_name

  subnet_ids = module.network.private_subnet_ids

  security_group_ids = [
    module.network.security_group_id
  ]

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "observability" {
  source = "./modules/observability"

  aws_region = var.aws_region

  kinesis_stream_name           = module.kinesis.stream_name
  firehose_delivery_stream_name = module.firehose.delivery_stream_name
  glue_job_name                 = module.glue.job_name

  ecs_cluster_name = "healthcare-realtime-data-jobs"
  alarm_topic_arn  = module.realtime_observability.alert_topic_arn

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "dbt_ecs" {
  source = "./modules/dbt_ecs"

  vpc_id                    = module.network.vpc_id
  private_subnet_ids        = module.network.private_subnet_ids
  data_bucket_name          = module.raw_s3.bucket_name
  image_tag                 = var.dbt_image_tag
  openlineage_collector_url = var.openlineage_collector_url

  source_database_name = "healthcare_realtime"
  dbt_database_name    = "healthcare_realtime_dbt"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "soda_ecs" {
  source = "./modules/soda_ecs"

  vpc_id                    = module.network.vpc_id
  private_subnet_ids        = module.network.private_subnet_ids
  data_bucket_name          = module.raw_s3.bucket_name
  image_tag                 = var.soda_image_tag
  openlineage_collector_url = var.openlineage_collector_url

  source_database_name = "healthcare_realtime"
  dbt_database_name    = "healthcare_realtime_dbt"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "vitals_simulator_ecs" {
  source = "./modules/vitals_simulator_ecs"

  aws_region = var.aws_region

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids

  ecs_cluster_arn = module.hapi_ecs.cluster_arn
  fhir_base_url   = module.hapi_ecs.fhir_base_url

  data_bucket_name = module.raw_s3.bucket_name
  image_tag        = var.vitals_simulator_image_tag
  alarm_topic_arn  = module.realtime_observability.alert_topic_arn

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "realtime_vitals" {
  source = "./modules/realtime_vitals"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
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
  websocket_stage_name     = "development"
  failure_queue_arn        = module.realtime_failure_handling.vitals_failures_queue_arn

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "realtime_websocket" {
  source = "./modules/realtime_websocket"

  depends_on = [aws_api_gateway_account.cloudwatch]

  aws_region = var.aws_region

  connections_table_name = module.realtime_vitals.websocket_connections_table_name
  connections_table_arn  = module.realtime_vitals.websocket_connections_table_arn
  lambda_zip_path        = "${path.root}/../build/lambda/websocket_handler.zip"
  patient_access_policy  = jsonencode(var.realtime_patient_access_policy)

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "vitals_api" {
  source = "./modules/vitals_api"

  depends_on = [aws_api_gateway_account.cloudwatch]

  aws_region = var.aws_region

  latest_vitals_table_name = module.realtime_vitals.latest_vitals_table_name
  latest_vitals_table_arn  = module.realtime_vitals.latest_vitals_table_arn

  lambda_zip_path       = "${path.root}/../build/lambda/vitals_api.zip"
  patient_access_policy = jsonencode(var.realtime_patient_access_policy)

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "realtime_observability" {
  source = "./modules/realtime_observability"

  aws_region = var.aws_region

  lambda_function_name = module.realtime_processor.lambda_function_name
  environment          = "development"
  alert_email          = var.realtime_alert_email
  replay_dlq_name      = module.realtime_failure_handling.vitals_replay_dlq_name

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "realtime_failure_handling" {
  source = "./modules/realtime_failure_handling"

  environment = "development"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "realtime_replay" {
  source = "./modules/realtime_replay"

  aws_region = var.aws_region

  kinesis_stream_arn = module.kinesis.stream_arn
  failure_queue_arn  = module.realtime_failure_handling.vitals_failures_queue_arn
  replay_dlq_arn     = module.realtime_failure_handling.vitals_replay_dlq_arn
  replay_dlq_url     = module.realtime_failure_handling.vitals_replay_dlq_url
  lambda_zip_path    = "${path.root}/../build/lambda/vitals_replay.zip"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "hapi_ecs" {
  source = "./modules/hapi_ecs"

  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}
