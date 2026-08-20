resource "aws_kinesis_stream" "vitals_events" {
  name             = var.stream_name
  retention_period = var.retention_period_hours

  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"

  stream_mode_details {
    stream_mode = var.stream_mode
  }

  tags = var.tags
}