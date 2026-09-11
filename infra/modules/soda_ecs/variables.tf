variable "vpc_id" {
  description = "VPC used by the Soda ECS task."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets used by the Soda Fargate task."
  type        = list(string)
}

variable "data_bucket_name" {
  description = "Healthcare data bucket."
  type        = string
}

variable "source_database_name" {
  description = "Glue database containing source healthcare data."
  type        = string
  default     = "healthcare_realtime"
}

variable "dbt_database_name" {
  description = "Glue database containing dbt models."
  type        = string
  default     = "healthcare_realtime_dbt"
}

variable "image_tag" {
  description = "ECR image tag used by the Soda ECS task."
  type        = string
  default     = "latest"
}

variable "openlineage_collector_url" {
  description = "Optional shared OpenLineage HTTP collector base URL."
  type        = string
  default     = ""
}

variable "openlineage_collector_invoke_arn" {
  description = "Optional execute-api ARN for the managed OpenLineage ingestion route."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to Soda ECS resources."
  type        = map(string)
  default     = {}
}
