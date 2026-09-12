output "ecr_repository_url" {
  description = "ECR repository containing the hardened Marquez image."
  value       = aws_ecr_repository.marquez.repository_url
}

output "image_tag_mutability" {
  description = "Configured ECR tag mutability used by deployment contract tests."
  value       = aws_ecr_repository.marquez.image_tag_mutability
}

output "collector_url" {
  description = "IAM-authorized OpenLineage collector base URL, or null when disabled."
  value       = var.enabled ? "https://${aws_apigatewayv2_api.marquez[0].id}.execute-api.${data.aws_region.current.region}.amazonaws.com/${var.stage_name}" : null
}

output "invoke_arn" {
  description = "ARN granting POST access to the OpenLineage ingestion route, or null when disabled."
  value       = var.enabled ? "${aws_apigatewayv2_api.marquez[0].execution_arn}/${var.stage_name}/POST/api/v1/lineage" : null
}

output "ingestion_authorization_type" {
  description = "Authorization mode protecting OpenLineage ingestion, or null when disabled."
  value       = var.enabled ? aws_apigatewayv2_route.lineage[0].authorization_type : null
}

output "service_name" {
  description = "Marquez ECS service name, or null when disabled."
  value       = var.enabled ? aws_ecs_service.marquez[0].name : null
}

output "alarm_names" {
  description = "CloudWatch alarms monitoring the managed collector, empty during intentional shutdown."
  value = concat(
    aws_cloudwatch_metric_alarm.no_lineage_events[*].alarm_name,
    aws_cloudwatch_metric_alarm.task_count[*].alarm_name,
    aws_cloudwatch_metric_alarm.unhealthy_targets[*].alarm_name,
    aws_cloudwatch_metric_alarm.target_5xx[*].alarm_name,
    aws_cloudwatch_metric_alarm.api_5xx[*].alarm_name,
  )
}

output "database_endpoint" {
  description = "Private Marquez PostgreSQL endpoint, or null when disabled."
  value       = var.enabled ? aws_db_instance.marquez[0].endpoint : null
  sensitive   = true
}
