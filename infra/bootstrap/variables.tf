variable "aws_region" {
  description = "AWS region containing the Terraform state bucket."
  type        = string
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket dedicated to persistent Terraform state."
  type        = string
}

variable "noncurrent_version_retention_days" {
  description = "Days to retain noncurrent Terraform state versions."
  type        = number
  default     = 90

  validation {
    condition     = var.noncurrent_version_retention_days >= 30
    error_message = "Terraform state versions must be retained for at least 30 days."
  }
}
