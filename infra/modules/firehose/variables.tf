variable "delivery_stream_name" {
  description = "Amazon Data Firehose delivery stream name"
  type        = string
}

variable "kinesis_stream_arn" {
  description = "ARN of the Kinesis Data Stream used as the Firehose source"
  type        = string
}

variable "s3_bucket_arn" {
  description = "ARN of the raw S3 destination bucket"
  type        = string
}

variable "tags" {
  description = "Tags assigned to Firehose resources"
  type        = map(string)
  default     = {}
}