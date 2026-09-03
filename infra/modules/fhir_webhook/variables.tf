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

variable "webhook_secret_id" {
  description = "Secrets Manager identifier containing the shared HAPI FHIR webhook secret."
  type        = string
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
}
