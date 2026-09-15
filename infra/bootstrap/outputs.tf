output "state_bucket_name" {
  description = "Persistent bucket used by the main Terraform stack."
  value       = aws_s3_bucket.terraform_state.id
}

output "aws_region" {
  description = "AWS region containing the persistent state bucket."
  value       = var.aws_region
}

output "main_backend_key" {
  description = "Recommended state key for the development application stack."
  value       = "healthcare-realtime-monitoring/terraform/terraform.tfstate"
}
