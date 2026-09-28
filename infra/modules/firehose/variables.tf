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

variable "data_classification" {
  description = "Data classification applied as the DataClassification tag on resources that hold data."
  type        = string
  validation {
    condition     = contains(["Public", "Synthetic", "Internal", "Confidential", "Restricted"], var.data_classification)
    error_message = "data_classification must be Public, Synthetic, Internal, Confidential or Restricted."
  }
}
