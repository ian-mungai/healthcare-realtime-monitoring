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