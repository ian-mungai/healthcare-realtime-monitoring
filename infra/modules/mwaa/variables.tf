variable "environment_name" {
  description = "Amazon MWAA environment name"
  type        = string
}

variable "source_bucket_name" {
  description = "S3 bucket used by Amazon MWAA"
  type        = string
}

variable "data_bucket_name" {
  description = "Healthcare realtime data bucket"
  type        = string
}

variable "glue_job_name" {
  description = "Glue job orchestrated by MWAA"
  type        = string
}

variable "glue_database_name" {
  description = "Glue database queried by MWAA"
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs used by MWAA"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups used by MWAA"
  type        = list(string)
}

variable "dbt_ecs_task_definition_arn" {
  description = "dbt ECS task definition ARN."
  type        = string
}

variable "dbt_ecs_task_role_arn" {
  description = "dbt ECS task role ARN."
  type        = string
}

variable "dbt_ecs_task_execution_role_arn" {
  description = "dbt ECS task execution role ARN."
  type        = string
}

variable "dbt_ecs_security_group_id" {
  description = "Security group used by dbt ECS tasks."
  type        = string
}

variable "dbt_ecs_subnet_ids" {
  description = "Private subnet IDs used by dbt ECS tasks."
  type        = list(string)
}

variable "tags" {
  description = "Tags applied to MWAA resources"
  type        = map(string)
  default     = {}
}

variable "soda_ecs_task_definition_arn" {
  description = "Soda ECS task definition ARN."
  type        = string
}

variable "soda_ecs_task_role_arn" {
  description = "Soda ECS task role ARN."
  type        = string
}

variable "soda_ecs_task_execution_role_arn" {
  description = "Soda ECS task execution role ARN."
  type        = string
}

variable "soda_ecs_security_group_id" {
  description = "Security group used by Soda ECS tasks."
  type        = string
}

variable "soda_ecs_subnet_ids" {
  description = "Private subnet IDs used by Soda ECS tasks."
  type        = list(string)
}