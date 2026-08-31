variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
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
