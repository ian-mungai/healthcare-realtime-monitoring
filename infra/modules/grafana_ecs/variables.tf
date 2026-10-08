variable "enabled" {
  description = "Whether to run Grafana on ECS. The ECR repository exists either way, so the image can be pushed first."
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "VPC hosting the private Grafana task."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets for the Grafana task; it has no public address and no inbound rule."
  type        = list(string)
}

variable "ecs_cluster_arn" {
  description = "Existing ECS cluster ARN used by the Grafana service."
  type        = string
}

variable "image_tag" {
  description = "Immutable ECR image tag of the Grafana image built from deploy/grafana/Dockerfile."
  type        = string
  default     = "sha-bootstrap"

  validation {
    condition     = !var.enabled || (startswith(var.image_tag, "sha-") && var.image_tag != "sha-bootstrap")
    error_message = "image_tag must be a pushed sha-* tag when Grafana is enabled."
  }
}

variable "desired_count" {
  description = "Number of Grafana tasks to run. Use zero to stop it without removing it."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count must be zero or one: Grafana keeps its state in the task."
  }
}

variable "allow_destructive_teardown" {
  description = "Allow deleting the ECR repository while it still holds images, for a reviewed teardown."
  type        = bool
  default     = false
}

variable "data_bucket_name" {
  description = "Data lake bucket holding the processed, quarantine and dbt data and the Athena results."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup Grafana queries run in."
  type        = string
}

variable "athena_catalog_name" {
  description = "Athena data catalog holding the Glue databases."
  type        = string
}

variable "source_database_name" {
  description = "Glue database of the processed and quarantined observations."
  type        = string
}

variable "dbt_database_name" {
  description = "Glue database of the dbt models; the data source's default database."
  type        = string
}

variable "tags" {
  description = "Tags applied to the Grafana resources."
  type        = map(string)
  default     = {}
}
