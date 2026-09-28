variable "bucket_name" {
  description = "Healthcare realtime S3 bucket"
  type        = string
}

variable "database_name" {
  description = "Glue Data Catalog database"
  type        = string
}

variable "processed_table_name" {
  description = "Glue table containing processed FHIR observations."
  type        = string
}

variable "quarantine_table_name" {
  description = "Glue table containing quarantined FHIR observations."
  type        = string
}

variable "project_name" {
  description = "Project name used as the OpenLineage namespace."
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

variable "quarantine_path" {
  description = "S3 path for rejected FHIR Observation measurements"
  type        = string
}

variable "metrics_path" {
  description = "S3 path for Glue processing metrics"
  type        = string
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
  description = "Tags applied to Glue resources"
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

variable "enable_table_optimizers" {
  description = "Enable Glue managed compaction, snapshot retention and orphan-file deletion for the processed Iceberg table. Enable only after the Glue job has created the table."
  type        = bool
  default     = false
}

variable "snapshot_retention_days" {
  description = "Days an expired Iceberg snapshot is kept before the retention optimizer removes it."
  type        = number
  default     = 7
  validation {
    condition     = var.snapshot_retention_days >= 1
    error_message = "snapshot_retention_days must be at least 1."
  }
}

variable "snapshots_to_retain" {
  description = "Minimum number of Iceberg snapshots the retention optimizer always keeps."
  type        = number
  default     = 3
  validation {
    condition     = var.snapshots_to_retain >= 1
    error_message = "snapshots_to_retain must be at least 1."
  }
}

variable "orphan_file_retention_days" {
  description = "Days an unreferenced file must exist before orphan-file deletion removes it; longer than any Glue job run."
  type        = number
  default     = 7
  validation {
    condition     = var.orphan_file_retention_days >= 1
    error_message = "orphan_file_retention_days must be at least 1."
  }
}
