output "ecr_repository_url" {
  description = "ECR repository of the Grafana image."
  value       = aws_ecr_repository.grafana.repository_url
}

output "service_name" {
  description = "Grafana ECS service name, or null when disabled."
  value       = var.enabled ? aws_ecs_service.grafana[0].name : null
}

output "admin_secret_arn" {
  description = "Secrets Manager secret holding the Grafana admin password, or null when disabled."
  value       = var.enabled ? data.aws_secretsmanager_secret.admin[0].arn : null
}

output "container_port" {
  description = "Port Grafana listens on inside the task; operators reach it through an SSM port forward."
  value       = local.port
}
