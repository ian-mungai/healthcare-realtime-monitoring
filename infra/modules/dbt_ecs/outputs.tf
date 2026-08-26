output "ecr_repository_url" {
  description = "ECR repository containing the dbt image."
  value       = aws_ecr_repository.dbt.repository_url
}

output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.dbt.arn
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.dbt.name
}

output "task_definition_arn" {
  description = "dbt ECS task definition ARN."
  value       = aws_ecs_task_definition.dbt.arn
}

output "task_role_arn" {
  description = "IAM role used by the dbt container."
  value       = aws_iam_role.task.arn
}

output "task_execution_role_arn" {
  description = "IAM execution role used by ECS."
  value       = aws_iam_role.task_execution.arn
}

output "security_group_id" {
  description = "Security group used by dbt Fargate tasks."
  value       = aws_security_group.dbt.id
}
