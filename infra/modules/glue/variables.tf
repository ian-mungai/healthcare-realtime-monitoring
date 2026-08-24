variable "bucket_name" {
  description = "Healthcare realtime S3 bucket"
  type        = string
}

variable "database_name" {
  description = "Glue Data Catalog database"
  type        = string
}

variable "job_name" {
  description = "Glue ETL job name"
  type        = string
}

variable "script_key" {
  description = "S3 key containing the Glue PySpark script"
  type        = string
}

variable "tags" {
  description = "Tags applied to Glue resources"
  type        = map(string)
  default     = {}
}