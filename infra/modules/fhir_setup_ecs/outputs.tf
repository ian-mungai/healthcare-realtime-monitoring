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
