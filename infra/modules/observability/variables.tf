variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "kinesis_stream_name" {
  description = "Healthcare vitals Kinesis stream name."
  type        = string
}

variable "firehose_delivery_stream_name" {
  description = "Healthcare Firehose delivery stream name."
  type        = string
}

variable "glue_job_name" {
  description = "Healthcare raw-to-processed Glue job name."
  type        = string
}

variable "ecs_cluster_name" {
  description = "Shared ECS cluster for data jobs."
  type        = string
}

variable "tags" {
  description = "Tags for observability resources."
  type        = map(string)
  default     = {}
}

variable "dbt_task_definition_family" {
  description = "dbt ECS task-definition family."
  type        = string
  default     = "healthcare_realtime_dbt"
}

variable "soda_task_definition_family" {
  description = "Soda ECS task-definition family."
  type        = string
  default     = "healthcare_realtime_soda"
}
