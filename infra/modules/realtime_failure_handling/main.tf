resource "aws_sqs_queue" "vitals_failures" {
  name                      = "healthcare-realtime-vitals-failures-${var.environment}"
  message_retention_seconds = 1209600
  receive_wait_time_seconds = 20
  sqs_managed_sse_enabled   = true

  tags = var.tags
}