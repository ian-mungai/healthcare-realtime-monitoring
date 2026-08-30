resource "aws_sqs_queue" "vitals_replay_dlq" {
  name                      = "healthcare-realtime-vitals-replay-dlq-${var.environment}"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = var.tags
}

resource "aws_sqs_queue" "vitals_failures" {
  name                       = "healthcare-realtime-vitals-failures-${var.environment}"
  message_retention_seconds  = 1209600
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = 180
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.vitals_replay_dlq.arn
    maxReceiveCount     = 5
  })

  tags = var.tags
}

resource "aws_sqs_queue_redrive_allow_policy" "vitals_replay_dlq" {
  queue_url = aws_sqs_queue.vitals_replay_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns = [
      aws_sqs_queue.vitals_failures.arn
    ]
  })
}