output "dashboard_name" {
  description = "Healthcare realtime CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.healthcare_realtime.dashboard_name
}

output "pipeline_failure_alarm_name" {
  description = "Pipeline task failure alarm name."
  value       = aws_cloudwatch_metric_alarm.pipeline_task_failure.alarm_name
}

output "kinesis_throttling_alarm_name" {
  description = "Kinesis throttling alarm name."
  value       = aws_cloudwatch_metric_alarm.kinesis_write_throttling.alarm_name
}

output "firehose_delivery_failure_alarm_name" {
  description = "Firehose delivery freshness alarm name."
  value       = aws_cloudwatch_metric_alarm.firehose_delivery_failure.alarm_name
}

output "live_processing_latency_alarm_name" {
  description = "Name of the live processing latency CloudWatch alarm."
  value       = aws_cloudwatch_metric_alarm.live_processing_latency.alarm_name
}

output "websocket_delivery_failure_alarm_name" {
  description = "Name of the WebSocket delivery failure CloudWatch alarm."
  value       = aws_cloudwatch_metric_alarm.websocket_delivery_failure.alarm_name
}