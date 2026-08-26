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
        y      = 14
        width  = 12
        height = 6

        properties = {
          title  = "MWAA Running / Queued Tasks"
          region = var.aws_region

          metrics = [
            [
              "AWS/MWAA",
              "RunningTasks",
              "Environment",
              var.mwaa_environment_name
            ],
            [
              ".",
              "QueuedTasks",
              ".",
              "."
            ]
          ]

          period = 300
          stat   = "Maximum"
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 14
        width  = 12
        height = 6

        properties = {
          title  = "MWAA Queue Age"
          region = var.aws_region

          metrics = [
            [
              "AWS/MWAA",
              "ApproximateAgeOfOldestTask",
              "Environment",
              var.mwaa_environment_name
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
        x      = 0
        y      = 20
        width  = 24
        height = 6

        properties = {
          title  = "MWAA WebServer / Worker CPU"
          region = var.aws_region

          metrics = [
            [
              "AWS/MWAA",
              "CPUUtilization",
              "Cluster",
              "WebServer",
              "Environment",
              var.mwaa_environment_name
            ],
            [
              ".",
              "CPUUtilization",
              ".",
              "BaseWorker",
              ".",
              "."
            ]
          ]

          period = 300
          stat   = "Average"
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

resource "aws_cloudwatch_metric_alarm" "mwaa_queue_age" {
  alarm_name        = "healthcare-realtime-mwaa-queue-age"
  alarm_description = "MWAA has tasks waiting in the queue for an excessive period."

  namespace   = "AWS/MWAA"
  metric_name = "ApproximateAgeOfOldestTask"
  statistic   = "Maximum"

  period             = 300
  evaluation_periods = 2
  threshold          = 600

  comparison_operator = "GreaterThanThreshold"

  dimensions = {
    Environment = var.mwaa_environment_name
  }

  treat_missing_data = "notBreaching"

  tags = var.tags
}