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

module "raw_s3" {
  source = "./modules/raw_s3"

  bucket_name = "imungai-healthcare-realtime"

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

  bucket_name     = module.raw_s3.bucket_name
  database_name   = "healthcare_realtime"
  job_name        = "healthcare_realtime_raw_to_processed"
  script_key      = "scripts/glue/fhir_observations_raw_to_processed.py"
  quarantine_path = "s3://${module.raw_s3.bucket_name}/quarantine/fhir_observations/"
  metrics_path    = "s3://${module.raw_s3.bucket_name}/metrics/glue/"

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

  environment_name   = "healthcare_realtime_mwaa"
  source_bucket_name = "imungai-healthcare-realtime-mwaa"
  data_bucket_name   = module.raw_s3.bucket_name

  dbt_ecs_task_definition_arn     = module.dbt_ecs.task_definition_arn
  dbt_ecs_task_role_arn           = module.dbt_ecs.task_role_arn
  dbt_ecs_task_execution_role_arn = module.dbt_ecs.task_execution_role_arn
  dbt_ecs_security_group_id       = module.dbt_ecs.security_group_id
  dbt_ecs_subnet_ids              = module.network.private_subnet_ids

  soda_ecs_task_definition_arn     = module.soda_ecs.task_definition_arn
  soda_ecs_task_role_arn           = module.soda_ecs.task_role_arn
  soda_ecs_task_execution_role_arn = module.soda_ecs.task_execution_role_arn
  soda_ecs_security_group_id       = module.soda_ecs.security_group_id
  soda_ecs_subnet_ids              = module.network.private_subnet_ids

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

  aws_region = "us-east-1"

  kinesis_stream_name           = module.kinesis.stream_name
  firehose_delivery_stream_name = module.firehose.delivery_stream_name
  glue_job_name                 = module.glue.job_name

  ecs_cluster_name      = "healthcare-realtime-data-jobs"
  mwaa_environment_name = "healthcare_realtime_mwaa"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

module "dbt_ecs" {
  source = "./modules/dbt_ecs"

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  data_bucket_name   = "imungai-healthcare-realtime"

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

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  data_bucket_name   = "imungai-healthcare-realtime"

  source_database_name = "healthcare_realtime"
  dbt_database_name    = "healthcare_realtime_dbt"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}
