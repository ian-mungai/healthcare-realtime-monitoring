variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the realtime vitals processor Lambda function."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "tags" {
  description = "Tags applied to supported observability resources."
  type        = map(string)
}

variable "alert_email" {
  description = "Email address subscribed to realtime CloudWatch alarm notifications."
  type        = string
}