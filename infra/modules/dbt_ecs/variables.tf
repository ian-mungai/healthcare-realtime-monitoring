variable "vpc_id" {
  description = "VPC used by the dbt ECS task."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets used by the dbt Fargate task."
  type        = list(string)
}

variable "data_bucket_name" {
  description = "Healthcare data bucket."
  type        = string
}

variable "source_database_name" {
  description = "Glue database containing the processed source table."
  type        = string
  default     = "healthcare_realtime"
}

variable "dbt_database_name" {
  description = "Glue database containing dbt-managed models."
  type        = string
  default     = "healthcare_realtime_dbt"
}

variable "image_tag" {
  description = "ECR image tag used by the dbt ECS task."
  type        = string
  default     = "latest"
}

variable "tags" {
  description = "Tags applied to dbt ECS resources."
  type        = map(string)
  default     = {}
}
