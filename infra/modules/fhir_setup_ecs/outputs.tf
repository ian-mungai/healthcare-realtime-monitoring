output "task_definition_family" {
  description = "Family of the FHIR setup task definition."
  value       = aws_ecs_task_definition.fhir_setup.family
}

output "security_group_id" {
  description = "Security group used by the FHIR setup task."
  value       = aws_security_group.fhir_setup.id
}

output "log_group_name" {
  description = "CloudWatch log group of the FHIR setup task."
  value       = aws_cloudwatch_log_group.fhir_setup.name
}

output "task_role_arn" {
  description = "Task role of the FHIR setup task, passed by the daily workflow."
  value       = aws_iam_role.task.arn
}

output "task_execution_role_arn" {
  description = "Execution role of the FHIR setup task, passed by the daily workflow."
  value       = aws_iam_role.task_execution.arn
}
