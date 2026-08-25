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

variable "tags" {
  description = "Tags applied to MWAA resources"
  type        = map(string)
  default     = {}
}