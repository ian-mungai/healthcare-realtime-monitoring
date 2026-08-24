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

  bucket_name   = module.raw_s3.bucket_name
  database_name = "healthcare_realtime"
  job_name      = "healthcare_realtime_raw_to_processed"
  script_key    = "scripts/glue/fhir_observations_raw_to_processed.py"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }

  depends_on = [
    module.raw_s3,
  ]
}
