output "ecr_repository_name" {
  description = "Name of the vitals simulator ECR repository."
  value       = aws_ecr_repository.vitals_simulator.name
}

output "ecr_repository_url" {
  description = "URL of the vitals simulator ECR repository."
  value       = aws_ecr_repository.vitals_simulator.repository_url
}

output "ecr_repository_arn" {
  description = "ARN of the vitals simulator ECR repository."
  value       = aws_ecr_repository.vitals_simulator.arn
}

output "task_definition_arn" {
  description = "ARN of the vitals simulator ECS task definition."
  value       = aws_ecs_task_definition.vitals_simulator.arn
}

output "task_definition_family" {
  description = "Family of the vitals simulator ECS task definition."
  value       = aws_ecs_task_definition.vitals_simulator.family
}

output "task_execution_role_arn" {
  description = "ARN of the vitals simulator ECS task execution role."
  value       = aws_iam_role.task_execution.arn
}

output "task_role_arn" {
  description = "ARN of the vitals simulator ECS task role."
  value       = aws_iam_role.task.arn
}

output "security_group_id" {
  description = "Security group used by vitals simulator ECS tasks."
  value       = aws_security_group.vitals_simulator.id
}

output "log_group_name" {
  description = "CloudWatch log group used by vitals simulator ECS tasks."
  value       = aws_cloudwatch_log_group.vitals_simulator.name
}

output "ecs_cluster_arn" {
  description = "ARN of the shared ECS cluster used by the vitals simulator."
  value       = var.ecs_cluster_arn
}
