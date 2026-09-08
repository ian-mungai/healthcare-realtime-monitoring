data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  metric_namespace = "HealthcareRealtime/Live"
  alert_topic_name = "healthcare-realtime-alerts-${var.environment}"
  alert_topic_arn  = "arn:${data.aws_partition.current.partition}:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${local.alert_topic_name}"
}

resource "aws_cloudwatch_dashboard" "realtime" {
  dashboard_name = "healthcare-realtime-live-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6

        properties = {
          title  = "Live Vitals Processing"
          view   = "timeSeries"
          region = var.aws_region
          stat   = "Sum"
          period = 60

          metrics = [
            [local.metric_namespace, "RecordsProcessed"],
            [local.metric_namespace, "WebSocketDeliveries"]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6

        properties = {
          title  = "Live Processing Latency"
          view   = "timeSeries"
          region = var.aws_region
          stat   = "Average"
          period = 60

          metrics = [
            [local.metric_namespace, "ProcessingLatencyMilliseconds"]
          ]

          annotations = {
            horizontal = [
              {
                label = "5 second alert threshold"
                value = 5000
              }
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6

        properties = {
          title  = "Active WebSocket Connections"
          view   = "timeSeries"
          region = var.aws_region
          stat   = "Maximum"
          period = 60

          metrics = [
            [local.metric_namespace, "ActiveConnections"]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6

        properties = {
          title  = "Live Path Health"
          view   = "timeSeries"
          region = var.aws_region
          stat   = "Sum"
          period = 60

          metrics = [
            [local.metric_namespace, "WebSocketDeliveryFailures"],
            [
              "AWS/Lambda",
              "Errors",
              "FunctionName",
              var.lambda_function_name
            ],
            [
              "AWS/Lambda",
              "Throttles",
              "FunctionName",
              var.lambda_function_name
            ]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6

        properties = {
          title  = "Kinesis Consumer Lag"
          view   = "timeSeries"
          region = var.aws_region
          stat   = "Maximum"
          period = 60

          metrics = [
            [
              "AWS/Lambda",
              "IteratorAge",
              "FunctionName",
              var.lambda_function_name
            ]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 24
        height = 6

        properties = {
          title  = "Terminal Replay DLQ"
          view   = "timeSeries"
          region = var.aws_region
          stat   = "Maximum"
          period = 60

          metrics = [
            [
              "AWS/SQS",
              "ApproximateNumberOfMessagesVisible",
              "QueueName",
              var.replay_dlq_name
            ]
          ]
        }
      }
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "processing_latency" {
  alarm_name        = "healthcare-realtime-processing-latency-${var.environment}"
  alarm_description = "Realtime vital processing latency has exceeded the 15-second, three-publication-interval threshold."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2

  namespace   = local.metric_namespace
  metric_name = "ProcessingLatencyMilliseconds"

  statistic = "Average"
  period    = 60
  threshold = 15000

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  ok_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "websocket_delivery_failures" {
  alarm_name        = "healthcare-realtime-websocket-delivery-failures-${var.environment}"
  alarm_description = "One or more realtime WebSocket deliveries failed."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  namespace   = local.metric_namespace
  metric_name = "WebSocketDeliveryFailures"

  statistic = "Sum"
  period    = 60
  threshold = 1

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  ok_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "processor_errors" {
  alarm_name        = "healthcare-realtime-processor-errors-${var.environment}"
  alarm_description = "The realtime vitals processor Lambda is reporting errors."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = var.lambda_function_name
  }

  statistic = "Sum"
  period    = 60
  threshold = 1

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  ok_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "processor_throttles" {
  alarm_name        = "healthcare-realtime-processor-throttles-${var.environment}"
  alarm_description = "The realtime vitals processor Lambda is being throttled."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  namespace   = "AWS/Lambda"
  metric_name = "Throttles"

  dimensions = {
    FunctionName = var.lambda_function_name
  }

  statistic = "Sum"
  period    = 60
  threshold = 1

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  ok_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name        = "healthcare-realtime-kinesis-iterator-age-${var.environment}"
  alarm_description = "The realtime Lambda consumer is falling behind the Kinesis stream."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2

  namespace   = "AWS/Lambda"
  metric_name = "IteratorAge"

  dimensions = {
    FunctionName = var.lambda_function_name
  }

  statistic = "Maximum"
  period    = 60
  threshold = 10000

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  ok_actions = [
    aws_sns_topic.realtime_alerts.arn
  ]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "replay_dlq_messages" {
  alarm_name        = "healthcare-realtime-replay-dlq-messages-${var.environment}"
  alarm_description = "The terminal replay DLQ contains records requiring operator investigation."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = var.replay_dlq_name
  }

  statistic = "Maximum"
  period    = 60
  threshold = 1

  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.realtime_alerts.arn]
  ok_actions    = [aws_sns_topic.realtime_alerts.arn]

  tags = var.tags
}

data "aws_iam_policy_document" "realtime_alerts_kms" {
  statement {
    sid    = "EnableAccountAdministration"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowSNSKeyUse"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*"
    ]

    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:sns:topicArn"
      values   = [local.alert_topic_arn]
    }
  }

  statement {
    sid    = "AllowCloudWatchAlarmPublishing"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*"
    ]

    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:cloudwatch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alarm:*"]
    }
  }
}

resource "aws_kms_key" "realtime_alerts" {
  description             = "Encrypts healthcare realtime alert notifications."
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.realtime_alerts_kms.json

  tags = var.tags
}

resource "aws_kms_alias" "realtime_alerts" {
  name          = "alias/healthcare-realtime-alerts-${var.environment}"
  target_key_id = aws_kms_key.realtime_alerts.key_id
}

resource "aws_sns_topic" "realtime_alerts" {
  name              = local.alert_topic_name
  kms_master_key_id = aws_kms_key.realtime_alerts.arn

  tags = var.tags
}

data "aws_iam_policy_document" "realtime_alerts_topic" {
  statement {
    sid    = "AllowAccountManagement"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions = [
      "SNS:AddPermission",
      "SNS:DeleteTopic",
      "SNS:GetTopicAttributes",
      "SNS:ListSubscriptionsByTopic",
      "SNS:Publish",
      "SNS:Receive",
      "SNS:RemovePermission",
      "SNS:SetTopicAttributes",
      "SNS:Subscribe"
    ]

    resources = [aws_sns_topic.realtime_alerts.arn]
  }

  statement {
    sid    = "AllowCloudWatchAlarmPublishing"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.realtime_alerts.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:cloudwatch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alarm:*"]
    }
  }
}

resource "aws_sns_topic_policy" "realtime_alerts" {
  arn    = aws_sns_topic.realtime_alerts.arn
  policy = data.aws_iam_policy_document.realtime_alerts_topic.json
}

resource "aws_sns_topic_subscription" "realtime_alert_email" {
  topic_arn = aws_sns_topic.realtime_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
