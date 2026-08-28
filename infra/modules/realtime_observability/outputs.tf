output "dashboard_name" {
  description = "Name of the realtime CloudWatch dashboard."
  value       = aws_cloudwatch_dashboard.realtime.dashboard_name
}

output "processing_latency_alarm_name" {
  description = "Name of the realtime processing latency alarm."
  value       = aws_cloudwatch_metric_alarm.processing_latency.alarm_name
}

output "websocket_delivery_failure_alarm_name" {
  description = "Name of the WebSocket delivery failure alarm."
  value       = aws_cloudwatch_metric_alarm.websocket_delivery_failures.alarm_name
}

output "processor_error_alarm_name" {
  description = "Name of the realtime processor Lambda error alarm."
  value       = aws_cloudwatch_metric_alarm.processor_errors.alarm_name
}

output "processor_throttle_alarm_name" {
  description = "Name of the realtime processor Lambda throttle alarm."
  value       = aws_cloudwatch_metric_alarm.processor_throttles.alarm_name
}

output "iterator_age_alarm_name" {
  description = "Name of the Kinesis consumer iterator-age alarm."
  value       = aws_cloudwatch_metric_alarm.iterator_age.alarm_name
}

output "alert_topic_arn" {
  description = "ARN of the realtime alert SNS topic."
  value       = aws_sns_topic.realtime_alerts.arn
}

output "alert_topic_name" {
  description = "Name of the realtime alert SNS topic."
  value       = aws_sns_topic.realtime_alerts.name
}