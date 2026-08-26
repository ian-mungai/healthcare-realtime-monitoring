output "ecr_repository_url" {
  description = "ECR repository containing the Soda image."
  value       = aws_ecr_repository.soda.repository_url
}

output "task_definition_arn" {
  description = "Soda ECS task definition ARN."
  value       = aws_ecs_task_definition.soda.arn
}

output "task_role_arn" {
  description = "IAM role used by the Soda container."
  value       = aws_iam_role.task.arn
}

output "task_execution_role_arn" {
  description = "IAM execution role used by ECS."
  value       = aws_iam_role.task_execution.arn
}

output "security_group_id" {
  description = "Security group used by Soda Fargate tasks."
  value       = aws_security_group.soda.id
}