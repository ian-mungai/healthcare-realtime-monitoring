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

output "seed_bundles_s3_prefix" {
  description = "S3 prefix where the Synthea bundles are uploaded."
  value       = var.seed_bundles_s3_prefix
}
