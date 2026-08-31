variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "api_id" {
  description = "ID of the existing realtime HTTP API."
  type        = string
}

variable "api_endpoint" {
  description = "Base endpoint of the existing realtime HTTP API."
  type        = string
}

variable "kinesis_stream_name" {
  description = "Name of the realtime vitals Kinesis stream."
  type        = string
}

variable "kinesis_stream_arn" {
  description = "ARN of the realtime vitals Kinesis stream."
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to the FHIR webhook Lambda deployment package."
  type        = string
}

variable "webhook_secret" {
  description = "Shared secret required for HAPI FHIR webhook requests."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
}
