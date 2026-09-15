variable "enabled" {
  description = "Whether to deploy the managed Marquez collector infrastructure."
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "VPC hosting the private collector service and database."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets used by Marquez, its database, load balancer, and API Gateway VPC link."
  type        = list(string)
}

variable "ecs_cluster_arn" {
  description = "Existing ECS cluster ARN used by the Marquez service."
  type        = string
}

variable "image_tag" {
  description = "Immutable ECR image tag used by the Marquez ECS service."
  type        = string
  default     = "sha-bootstrap"

  validation {
    condition     = !var.enabled || startswith(var.image_tag, "sha-")
    error_message = "image_tag must use an immutable sha-* tag when the collector is enabled."
  }
}

variable "desired_count" {
  description = "Number of Marquez ECS tasks to run. Use zero for cost-controlled shutdown."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count must be zero or one for this portfolio environment."
  }
}

variable "allow_destructive_teardown" {
  description = "Disable database deletion protection and allow populated ECR deletion for a reviewed teardown."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Skip the Marquez RDS final snapshot when deletion is enabled."
  type        = bool
  default     = false
}

variable "final_snapshot_identifier" {
  description = "Final Marquez snapshot identifier when skip_final_snapshot is false."
  type        = string
  default     = "healthcare-realtime-marquez-final"
}

variable "stage_name" {
  description = "API Gateway stage exposing the OpenLineage endpoint."
  type        = string
  default     = "development"
}

variable "alarm_topic_arn" {
  description = "SNS topic ARN used for managed OpenLineage collector alarms."
  type        = string
}

variable "tags" {
  description = "Tags applied to OpenLineage collector resources."
  type        = map(string)
  default     = {}
}
