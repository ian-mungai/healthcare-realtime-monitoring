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
  value       = "${var.project_name}/terraform/terraform.tfstate"
}

output "bootstrap_state_backup_key" {
  description = "Object key used for the bootstrap-state backup."
  value       = "${var.project_name}/terraform/bootstrap/terraform.tfstate"
}
