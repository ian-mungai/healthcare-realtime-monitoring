output "fhir_base_url" {
  description = "Public HAPI FHIR R4 base URL."
  value       = "http://${aws_lb.hapi.dns_name}/fhir"
}

output "load_balancer_dns_name" {
  description = "Public DNS name of the HAPI Application Load Balancer."
  value       = aws_lb.hapi.dns_name
}

output "cluster_name" {
  description = "ECS cluster hosting persistent realtime services."
  value       = aws_ecs_cluster.services.name
}

output "cluster_arn" {
  description = "ARN of the ECS cluster hosting persistent realtime services."
  value       = aws_ecs_cluster.services.arn
}

output "service_name" {
  description = "HAPI FHIR ECS service name."
  value       = aws_ecs_service.hapi.name
}

output "task_definition_arn" {
  description = "HAPI FHIR ECS task definition ARN."
  value       = aws_ecs_task_definition.hapi.arn
}

output "security_group_id" {
  description = "Security group used by the HAPI FHIR ECS service."
  value       = aws_security_group.hapi.id
}

output "database_endpoint" {
  description = "Private PostgreSQL endpoint used by HAPI FHIR."
  value       = aws_db_instance.hapi.endpoint
}