variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "realtime_alert_email" {
  description = "Email address used for realtime infrastructure alerts."
  type        = string
}