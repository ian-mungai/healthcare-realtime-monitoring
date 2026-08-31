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
