variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "data_bucket_name" {
  description = "Globally unique S3 bucket name for healthcare data."
  type        = string
}

variable "mwaa_source_bucket_name" {
  description = "Globally unique S3 bucket name for MWAA Serverless source artifacts."
  type        = string
}

variable "realtime_alert_email" {
  description = "Email address used for realtime infrastructure alerts."
  type        = string
}

variable "vitals_simulator_image_tag" {
  description = "Immutable ECR image tag used by the realtime vitals simulator."
  type        = string

  validation {
    condition     = startswith(var.vitals_simulator_image_tag, "sha-")
    error_message = "vitals_simulator_image_tag must use an immutable sha-* tag."
  }
}

variable "dbt_image_tag" {
  description = "ECR image tag deployed by the dbt ECS task."
  type        = string
}

variable "soda_image_tag" {
  description = "ECR image tag deployed by the Soda ECS task."
  type        = string
}
