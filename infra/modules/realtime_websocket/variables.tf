variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "connections_table_name" {
  description = "DynamoDB table containing active WebSocket connections."
  type        = string
}

variable "connections_table_arn" {
  description = "ARN of the DynamoDB WebSocket connections table."
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to the packaged WebSocket handler Lambda zip."
  type        = string
}

variable "patient_access_policy" {
  description = "JSON map of IAM principal ARN patterns to authorized patient ID patterns."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied to realtime WebSocket resources."
  type        = map(string)
  default     = {}
}
