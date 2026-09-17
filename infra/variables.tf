variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "project_name" {
  description = "Project identifier used for tags and lineage namespaces."
  type        = string
}

variable "deployment_environment" {
  description = "Deployment environment name used by stages, tags, queues, dashboards, and alarms."
  type        = string
}

variable "kinesis_stream_name" {
  description = "Primary realtime Kinesis stream name."
  type        = string
}

variable "load_test_kinesis_stream_name" {
  description = "Isolated load-test Kinesis stream name."
  type        = string
}

variable "firehose_delivery_stream_name" {
  description = "Firehose delivery stream name."
  type        = string
}

variable "glue_job_name" {
  description = "Glue ETL job name."
  type        = string
}

variable "raw_prefix" {
  description = "S3 prefix containing raw FHIR observations."
  type        = string
}

variable "airflow_pipeline_schedule" {
  description = "Cron schedule used by both Airflow deployment targets."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup used by validation and analytics queries."
  type        = string
}

variable "athena_results_s3_uri" {
  description = "S3 URI used for Athena query results."
  type        = string
}

variable "source_database_name" {
  description = "Glue database containing processed source observations."
  type        = string
}

variable "processed_observations_table_name" {
  description = "Processed observation table name in the source Glue database."
  type        = string
}

variable "quarantine_table_name" {
  description = "Quarantined observation table name in the source Glue database."
  type        = string
}

variable "dbt_database_name" {
  description = "Glue database used for dbt analytical models."
  type        = string
}

variable "ml_database_name" {
  description = "Glue database containing published model predictions."
  type        = string
}

variable "ml_predictions_published_table_name" {
  description = "Published model-prediction table name."
  type        = string
}

variable "athena_catalog_name" {
  description = "Athena data catalog name used by dbt and quality tools."
  type        = string
}

variable "soda_data_source_name" {
  description = "Logical Soda data source name."
  type        = string
}

variable "dbt_staging_table_name" {
  description = "Physical name of the dbt staging model."
  type        = string
}

variable "dbt_dim_patient_table_name" {
  description = "Physical name of the patient dimension."
  type        = string
}

variable "dbt_dim_encounter_table_name" {
  description = "Physical name of the encounter dimension."
  type        = string
}

variable "dbt_dim_provider_table_name" {
  description = "Physical name of the provider dimension."
  type        = string
}

variable "dbt_dim_observation_type_table_name" {
  description = "Physical name of the observation-type dimension."
  type        = string
}

variable "dbt_dim_date_table_name" {
  description = "Physical name of the date dimension."
  type        = string
}

variable "dbt_fact_observations_table_name" {
  description = "Physical name of the observation fact table."
  type        = string
}

variable "dbt_encounter_features_table_name" {
  description = "Physical name of the encounter feature table."
  type        = string
}

variable "active_patient_ids" {
  description = "Exactly ten synthetic HAPI patient identifiers included in cohort analytics."
  type        = list(string)

  validation {
    condition     = length(var.active_patient_ids) == 10 && length(distinct(var.active_patient_ids)) == 10 && alltrue([for patient_id in var.active_patient_ids : trimspace(patient_id) != ""])
    error_message = "active_patient_ids must contain exactly ten unique non-empty patient identifiers."
  }
}

variable "dbt_ml_training_table_name" {
  description = "Physical name of the ML training table."
  type        = string
}

variable "dbt_ml_scoring_table_name" {
  description = "Physical name of the ML scoring table."
  type        = string
}

variable "dbt_ml_predictions_serving_table_name" {
  description = "Physical name of the ML predictions serving table."
  type        = string
}

variable "dbt_ml_predictions_latest_table_name" {
  description = "Physical name of the latest ML prediction view."
  type        = string
}

variable "latest_vitals_table_name" {
  description = "DynamoDB table containing the latest accepted patient vitals."
  type        = string
}

variable "processed_observations_state_table_name" {
  description = "DynamoDB table containing realtime idempotency claims."
  type        = string
}

variable "load_test_results_table_name" {
  description = "DynamoDB table containing isolated load-test results."
  type        = string
}

variable "websocket_connections_table_name" {
  description = "DynamoDB table containing active WebSocket connections."
  type        = string
}

variable "api_stage_name" {
  description = "API Gateway stage name used by HTTP and WebSocket APIs."
  type        = string
}

variable "fhir_webhook_secret_id" {
  description = "Secrets Manager identifier containing the FHIR webhook secret."
  type        = string
}

variable "data_bucket_name" {
  description = "Globally unique S3 bucket name for healthcare data."
  type        = string
}

variable "allow_destructive_teardown" {
  description = "Opt in to disabling deletion protection and allowing Terraform to empty managed S3/ECR resources during a reviewed teardown."
  type        = bool
  default     = false
}

variable "hapi_skip_final_snapshot" {
  description = "Skip the HAPI RDS final snapshot when deletion is enabled. Set false when a retained recovery snapshot is required."
  type        = bool
  default     = true
}

variable "openlineage_skip_final_snapshot" {
  description = "Skip the Marquez RDS final snapshot when deletion is enabled. Set true for a complete portfolio teardown."
  type        = bool
  default     = false
}

variable "openlineage_final_snapshot_identifier" {
  description = "Unique final snapshot identifier used when the Marquez final snapshot is retained."
  type        = string
  default     = "healthcare-realtime-marquez-final"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,62}$", var.openlineage_final_snapshot_identifier))
    error_message = "openlineage_final_snapshot_identifier must be a valid lowercase RDS snapshot identifier."
  }
}

variable "realtime_alert_email" {
  description = "Email address used for realtime infrastructure alerts."
  type        = string
}

variable "realtime_patient_access_policy" {
  description = "Map of IAM principal ARN patterns to authorized patient ID patterns for realtime APIs."
  type        = map(list(string))
  sensitive   = true
  default     = {}
}

variable "external_openlineage_collector_url" {
  description = "Optional external OpenLineage HTTP collector base URL. Empty retains durable S3 event storage when the managed collector is disabled."
  type        = string
  default     = ""

  validation {
    condition     = var.external_openlineage_collector_url == "" || can(regex("^https?://[^/]+", var.external_openlineage_collector_url))
    error_message = "external_openlineage_collector_url must be empty or an absolute HTTP or HTTPS URL."
  }
}

variable "enable_openlineage_collector" {
  description = "Deploy the managed IAM-authorized Marquez collector."
  type        = bool
  default     = false
}

variable "openlineage_collector_image_tag" {
  description = "Immutable ECR tag for the hardened Marquez collector image."
  type        = string
  default     = "sha-bootstrap"

  validation {
    condition     = !var.enable_openlineage_collector || startswith(var.openlineage_collector_image_tag, "sha-")
    error_message = "openlineage_collector_image_tag must use an immutable sha-* tag when the managed collector is enabled."
  }
}

variable "openlineage_collector_desired_count" {
  description = "Number of managed Marquez ECS tasks to run. Use zero for cost-controlled shutdown."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.openlineage_collector_desired_count)
    error_message = "openlineage_collector_desired_count must be zero or one."
  }
}

variable "enable_github_oidc" {
  description = "Create the repository-scoped GitHub Actions deployment identity."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deployment role, in owner/repository form."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_github_oidc || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/repository form when GitHub OIDC is enabled."
  }
}

variable "github_oidc_subject_prefix" {
  description = "Optional immutable GitHub OIDC repository subject prefix returned by the GitHub API."
  type        = string
  default     = ""

  validation {
    condition = var.github_oidc_subject_prefix == "" || can(regex(
      "^repo:[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?$",
      var.github_oidc_subject_prefix,
    ))
    error_message = "github_oidc_subject_prefix must be empty or use GitHub's repo:owner/repository subject-prefix format, optionally with immutable numeric IDs."
  }
}

variable "github_deployment_environment" {
  description = "Protected GitHub environment allowed to deploy."
  type        = string
}

variable "github_deployment_policy_arns" {
  description = "Existing least-privilege managed policy ARNs attached to the GitHub deployment role."
  type        = list(string)
  default     = []

  validation {
    condition     = !var.enable_github_oidc || length(var.github_deployment_policy_arns) > 0
    error_message = "github_deployment_policy_arns must contain at least one policy when GitHub OIDC is enabled."
  }

  validation {
    condition = !var.enable_github_oidc || alltrue([
      for policy_arn in var.github_deployment_policy_arns : can(regex("^arn:aws:iam::[0-9]{12}:policy/healthcare_realtime_", policy_arn))
    ])
    error_message = "GitHub deployment policies must be customer-managed healthcare_realtime_* policies in the target account."
  }
}

variable "vitals_simulator_image_tag" {
  description = "Immutable ECR image tag used by the realtime vitals simulator."
  type        = string

  validation {
    condition     = startswith(var.vitals_simulator_image_tag, "sha-")
    error_message = "vitals_simulator_image_tag must use an immutable sha-* tag."
  }
}

variable "dbt_image_tag" {
  description = "ECR image tag deployed by the dbt ECS task."
  type        = string
}

variable "ml_approved_model_version" {
  description = "Exact immutable model version approved for automated scoring. Leave empty only during first-deployment bootstrap."
  type        = string
  default     = ""

  validation {
    condition     = var.ml_approved_model_version == "" || can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.ml_approved_model_version))
    error_message = "ml_approved_model_version must be empty for bootstrap or a lowercase immutable version name."
  }
}

variable "soda_image_tag" {
  description = "ECR image tag deployed by the Soda ECS task."
  type        = string
}
