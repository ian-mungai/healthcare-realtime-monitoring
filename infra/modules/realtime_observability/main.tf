locals {
  metric_namespace = "HealthcareRealtime/Live"
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
          region = "us-east-1"
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
          region = "us-east-1"
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
          region = "us-east-1"
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
          region = "us-east-1"
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
          region = "us-east-1"
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
      }
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "processing_latency" {
  alarm_name        = "healthcare-realtime-processing-latency-${var.environment}"
  alarm_description = "Realtime vital processing latency has exceeded five seconds."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2

  namespace   = local.metric_namespace
  metric_name = "ProcessingLatencyMilliseconds"

  statistic = "Average"
  period    = 60
  threshold = 5000

  treat_missing_data = "notBreaching"

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

  tags = var.tags
}