variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "latest_vitals_table_name" {
  description = "Name of the DynamoDB table containing the latest patient vitals."
  type        = string
}

variable "latest_vitals_table_arn" {
  description = "ARN of the DynamoDB table containing the latest patient vitals."
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to the vitals API Lambda deployment package."
  type        = string
}

variable "patient_access_policy" {
  description = "JSON map of IAM principal ARN patterns to authorized patient ID patterns."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
}
