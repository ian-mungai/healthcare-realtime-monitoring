variable "vpc_id" {
  description = "VPC used by the Soda ECS task."
  type        = string
}

variable "data_bucket_name" {
  description = "Healthcare data bucket."
  type        = string
}

variable "source_database_name" {
  description = "Glue database containing source healthcare data."
  type        = string
}

variable "dbt_database_name" {
  description = "Glue database containing dbt models."
  type        = string
}

variable "ml_database_name" {
  description = "Glue database containing model prediction tables."
  type        = string
}

variable "data_identifiers" {
  description = "Database and table identifiers injected into the Soda and Great Expectations task environment."
  type        = map(string)
}

variable "image_tag" {
  description = "ECR image tag used by the Soda ECS task."
  type        = string
}

variable "force_delete_repository" {
  description = "Allow deletion of a populated Soda ECR repository during an explicitly approved teardown."
  type        = bool
  default     = false
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

variable "athena_workgroup_name" {
  description = "Athena workgroup the task runs queries in."
  type        = string
}

variable "athena_catalog_name" {
  description = "Athena data catalog the task reads metadata from."
  type        = string
}
