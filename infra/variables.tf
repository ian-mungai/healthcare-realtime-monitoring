variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "data_bucket_name" {
  description = "Globally unique S3 bucket name for healthcare data."
  type        = string
}

variable "mwaa_source_bucket_name" {
  description = "Globally unique S3 bucket name for MWAA Serverless source artifacts."
  type        = string
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

variable "openlineage_collector_url" {
  description = "Optional shared OpenLineage HTTP collector base URL. Empty retains durable S3 event storage."
  type        = string
  default     = ""

  validation {
    condition     = var.openlineage_collector_url == "" || can(regex("^https?://[^/]+", var.openlineage_collector_url))
    error_message = "openlineage_collector_url must be empty or an absolute HTTP or HTTPS URL."
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

variable "github_deployment_environment" {
  description = "Protected GitHub environment allowed to deploy."
  type        = string
  default     = "development"
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

variable "soda_image_tag" {
  description = "ECR image tag deployed by the Soda ECS task."
  type        = string
}
