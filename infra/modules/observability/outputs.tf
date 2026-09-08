output "dashboard_name" {
  description = "Healthcare realtime CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.healthcare_realtime.dashboard_name
}

output "kinesis_throttling_alarm_name" {
  description = "Kinesis throttling alarm name."
  value       = aws_cloudwatch_metric_alarm.kinesis_write_throttling.alarm_name
}

output "firehose_delivery_failure_alarm_name" {
  description = "Firehose delivery freshness alarm name."
  value       = aws_cloudwatch_metric_alarm.firehose_delivery_failure.alarm_name
}
