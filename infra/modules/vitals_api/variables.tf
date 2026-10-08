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

variable "stage_name" {
  description = "API Gateway deployment stage name."
  type        = string
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default     = {}
}

variable "early_warning_zip_path" {
  description = "Path to the packaged early-warning Lambda (scripts/lambda/build_early_warning.sh)."
  type        = string
}

variable "feature_window_table_name" {
  description = "DynamoDB table holding each encounter's feature-window readings and stored scores."
  type        = string
}

variable "feature_window_table_arn" {
  description = "ARN of the feature-window table."
  type        = string
}

variable "data_bucket_name" {
  description = "Bucket holding the published model artifacts."
  type        = string
}

variable "approved_model_version" {
  description = "Model version whose scoring parameters the endpoint uses; empty until a model is approved."
  type        = string
  default     = ""
}
