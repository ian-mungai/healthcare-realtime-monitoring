variable "kinesis_stream_arn" {
  description = "ARN of the realtime vitals Kinesis stream."
  type        = string
}

variable "failure_queue_arn" {
  description = "ARN of the realtime vitals failure queue."
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to the vitals replay Lambda deployment package."
  type        = string
}

variable "tags" {
  description = "Tags applied to replay resources."
  type        = map(string)
}
