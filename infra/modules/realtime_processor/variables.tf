variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "kinesis_stream_arn" {
  description = "ARN of the vitals Kinesis stream."
  type        = string
}

variable "latest_vitals_table_name" {
  description = "DynamoDB table storing latest patient vitals."
  type        = string
}

variable "latest_vitals_table_arn" {
  description = "ARN of the latest vitals DynamoDB table."
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to the packaged realtime processor Lambda zip."
  type        = string
}

variable "tags" {
  description = "Tags applied to realtime processor resources."
  type        = map(string)
  default     = {}
}

variable "connections_table_name" {
  description = "DynamoDB table containing active WebSocket connections."
  type        = string
}

variable "connections_table_arn" {
  description = "ARN of the DynamoDB WebSocket connections table."
  type        = string
}

variable "websocket_api_id" {
  description = "API Gateway WebSocket API ID."
  type        = string
}

variable "websocket_stage_name" {
  description = "API Gateway WebSocket stage name."
  type        = string
  default     = "development"
}

variable "failure_queue_arn" {
  description = "ARN of the SQS destination for discarded Kinesis records."
  type        = string
}