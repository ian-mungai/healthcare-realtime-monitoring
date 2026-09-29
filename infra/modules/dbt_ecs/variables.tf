variable "vpc_id" {
  description = "VPC used by the dbt ECS task."
  type        = string
}

variable "data_bucket_name" {
  description = "Healthcare data bucket."
  type        = string
}

variable "source_database_name" {
  description = "Glue database containing the processed source table."
  type        = string
}

variable "dbt_database_name" {
  description = "Glue database containing dbt-managed models."
  type        = string
}

variable "image_tag" {
  description = "ECR image tag used by the dbt ECS task."
  type        = string
}

variable "force_delete_repository" {
  description = "Allow deletion of a populated dbt ECR repository during an explicitly approved teardown."
  type        = bool
  default     = false
}

variable "approved_model_version" {
  description = "Exact immutable model version approved for automated scoring."
  type        = string
}

variable "ml_database_name" {
  description = "Glue database containing Terraform-managed model prediction tables."
  type        = string
}

variable "ml_predictions_published_table_name" {
  description = "Physical Glue table containing published model predictions."
  type        = string
}

variable "data_identifiers" {
  description = "Database and table identifiers injected into the dbt and ML task environment."
  type        = map(string)
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
  description = "Tags applied to dbt ECS resources."
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

variable "athena_workgroup_name" {
  description = "Athena workgroup the task runs queries in."
  type        = string
}

variable "athena_catalog_name" {
  description = "Athena data catalog the task reads metadata from."
  type        = string
}
