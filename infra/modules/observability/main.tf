resource "aws_cloudwatch_dashboard" "healthcare_realtime" {
  dashboard_name = "healthcare-realtime-monitoring"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 2

        properties = {
          markdown = "# Healthcare Realtime Monitoring"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 38
        width  = 12
        height = 6

        properties = {
          title   = "Live Vitals Processing"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false

          metrics = [
            [
              "HealthcareRealtime/Live",
              "RecordsProcessed",
              {
                stat  = "Sum"
                label = "Records Processed"
              }
            ],
            [
              ".",
              "WebSocketDeliveries",
              {
                stat  = "Sum"
                label = "WebSocket Deliveries"
              }
            ],
            [
              ".",
              "WebSocketDeliveryFailures",
              {
                stat  = "Sum"
                label = "WebSocket Delivery Failures"
              }
            ]
          ]

          period = 60
        }
        }, {
        type   = "metric"
        x      = 12
        y      = 38
        width  = 12
        height = 6

        properties = {
          title   = "Live Processing Latency"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false

          metrics = [
            [
              "HealthcareRealtime/Live",
              "ProcessingLatencyMilliseconds",
              {
                stat  = "Average"
                label = "Average"
              }
            ],
            [
              "...",
              {
                stat  = "Maximum"
                label = "Maximum"
              }
            ]
          ]

          period = 60

          yAxis = {
            left = {
              min   = 0
              label = "Milliseconds"
            }
          }

          annotations = {
            horizontal = [
              {
                label = "5 second threshold"
                value = 5000
              },
              {
                label = "3 second target"
                value = 3000
              }
            ]
          }
        }
        }, {
        type   = "metric"
        x      = 0
        y      = 44
        width  = 12
        height = 6

        properties = {
          title   = "Active WebSocket Connections"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false

          metrics = [
            [
              "HealthcareRealtime/Live",
              "ActiveConnections",
              {
                stat  = "Maximum"
                label = "Active Connections"
              }
            ]
          ]

          period = 60

          yAxis = {
            left = {
              min = 0
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 44
        width  = 12
        height = 6

        properties = {
          title   = "Live Path Health"
          region  = var.aws_region
          view    = "singleValue"
          stacked = false

          metrics = [
            [
              "HealthcareRealtime/Live",
              "RecordsProcessed",
              {
                stat  = "Sum"
                label = "Records"
              }
            ],
            [
              ".",
              "WebSocketDeliveries",
              {
                stat  = "Sum"
                label = "Deliveries"
              }
            ],
            [
              ".",
              "WebSocketDeliveryFailures",
              {
                stat  = "Sum"
                label = "Failures"
              }
            ],
            [
              ".",
              "ProcessingLatencyMilliseconds",
              {
                stat  = "Average"
                label = "Avg Latency (ms)"
              }
            ],
            [
              ".",
              "ActiveConnections",
              {
                stat  = "Maximum"
                label = "Connections"
              }
            ]
          ]

          period = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 2
        width  = 12
        height = 6

        properties = {
          title  = "Pipeline Task Success / Failure"
          region = var.aws_region

          metrics = [
            [
              "HealthcareRealtime/Pipeline",
              "TaskSuccess"
            ],
            [
              ".",
              "TaskFailure"
            ]
          ]

          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 2
        width  = 12
        height = 6

        properties = {
          title  = "Kinesis Incoming Records"
          region = var.aws_region

          metrics = [
            [
              "AWS/Kinesis",
              "IncomingRecords",
              "StreamName",
              var.kinesis_stream_name
            ]
          ]

          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },

      {
        type   = "metric"
        x      = 0
        y      = 8
        width  = 12
        height = 6

        properties = {
          title  = "Firehose Delivery to S3"
          region = var.aws_region

          metrics = [
            [
              "AWS/Firehose",
              "DeliveryToS3.Records",
              "DeliveryStreamName",
              var.firehose_delivery_stream_name
            ]
          ]

          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },

      {
        type   = "metric"
        x      = 12
        y      = 8
        width  = 12
        height = 6

        properties = {
          title  = "Firehose Data Freshness"
          region = var.aws_region

          metrics = [
            [
              "AWS/Firehose",
              "DeliveryToS3.DataFreshness",
              "DeliveryStreamName",
              var.firehose_delivery_stream_name
            ]
          ]

          period = 300
          stat   = "Maximum"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 20
        width  = 12
        height = 6

        properties = {
          title  = "Glue Bytes Read"
          region = var.aws_region

          metrics = [
            [
              "Glue",
              "glue.driver.aggregate.bytesRead",
              "JobName",
              var.glue_job_name,
              "JobRunId",
              "ALL",
              "Type",
              "count"
            ]
          ]

          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },

      {
        type   = "metric"
        x      = 12
        y      = 20
        width  = 12
        height = 6

        properties = {
          title  = "Glue Job Elapsed Time"
          region = var.aws_region

          metrics = [
            [
              "Glue",
              "glue.driver.aggregate.elapsedTime",
              "JobName",
              var.glue_job_name,
              "JobRunId",
              "ALL",
              "Type",
              "gauge"
            ]
          ]

          period = 300
          stat   = "Maximum"
          view   = "timeSeries"
        }
      },

      {
        type   = "metric"
        x      = 0
        y      = 26
        width  = 12
        height = 6

        properties = {
          title  = "dbt Fargate CPU / Memory"
          region = var.aws_region

          metrics = [
            [
              "ECS/ContainerInsights",
              "TaskCpuUtilization",
              "TaskDefinitionFamily",
              var.dbt_task_definition_family,
              "ClusterName",
              var.ecs_cluster_name
            ],
            [
              ".",
              "TaskMemoryUtilization",
              ".",
              ".",
              ".",
              "."
            ]
          ]

          period = 60
          stat   = "Average"
          view   = "timeSeries"
        }
      },

      {
        type   = "metric"
        x      = 12
        y      = 26
        width  = 12
        height = 6

        properties = {
          title  = "Soda Fargate CPU / Memory"
          region = var.aws_region

          metrics = [
            [
              "ECS/ContainerInsights",
              "TaskCpuUtilization",
              "TaskDefinitionFamily",
              var.soda_task_definition_family,
              "ClusterName",
              var.ecs_cluster_name
            ],
            [
              ".",
              "TaskMemoryUtilization",
              ".",
              ".",
              ".",
              "."
            ]
          ]

          period = 60
          stat   = "Average"
          view   = "timeSeries"
        }
      }
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "pipeline_task_failure" {
  alarm_name          = "healthcare-realtime-pipeline-task-failure"
  alarm_description   = "A healthcare realtime pipeline task reported a failure."
  namespace           = "HealthcareRealtime/Pipeline"
  metric_name         = "TaskFailure"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "kinesis_write_throttling" {
  alarm_name          = "healthcare-realtime-kinesis-write-throttling"
  alarm_description   = "Kinesis write throughput is being throttled."
  namespace           = "AWS/Kinesis"
  metric_name         = "WriteProvisionedThroughputExceeded"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  dimensions = {
    StreamName = var.kinesis_stream_name
  }

  treat_missing_data = "notBreaching"

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "firehose_delivery_failure" {
  alarm_name          = "healthcare-realtime-firehose-delivery-failure"
  alarm_description   = "Firehose delivery to S3 has excessive data freshness."
  namespace           = "AWS/Firehose"
  metric_name         = "DeliveryToS3.DataFreshness"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 900
  comparison_operator = "GreaterThanThreshold"

  dimensions = {
    DeliveryStreamName = var.firehose_delivery_stream_name
  }

  treat_missing_data = "notBreaching"

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "live_processing_latency" {
  alarm_name        = "healthcare-realtime-live-processing-latency"
  alarm_description = "Near-real-time vital processing latency exceeded the five-second threshold."

  namespace   = "HealthcareRealtime/Live"
  metric_name = "ProcessingLatencyMilliseconds"
  statistic   = "Average"

  period              = 60
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 5000

  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  tags = var.tags
}
resource "aws_cloudwatch_metric_alarm" "websocket_delivery_failure" {
  alarm_name        = "healthcare-realtime-websocket-delivery-failure"
  alarm_description = "One or more realtime WebSocket vital deliveries failed."

  namespace   = "HealthcareRealtime/Live"
  metric_name = "WebSocketDeliveryFailures"
  statistic   = "Sum"

  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1

  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  tags = var.tags
}