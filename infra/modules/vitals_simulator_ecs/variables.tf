variable "aws_region" {
  description = "AWS region containing the vitals simulator resources."
  type        = string
}

variable "vpc_id" {
  description = "VPC containing the vitals simulator task."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs available to vitals simulator tasks."
  type        = list(string)
}

variable "ecs_cluster_arn" {
  description = "ARN of the shared persistent-services ECS cluster."
  type        = string
}

variable "fhir_base_url" {
  description = "Cloud HAPI FHIR R4 base URL used by the simulator."
  type        = string
}

variable "data_bucket_name" {
  description = "S3 bucket containing the cloud FHIR resource mapping."
  type        = string
}

variable "resource_map_s3_key" {
  description = "S3 key containing the cloud FHIR resource mapping."
  type        = string
  default     = "config/vitals_simulator/fhir_resource_map.json"
}

variable "image_tag" {
  description = "Immutable simulator image tag."
  type        = string
}

variable "tags" {
  description = "Tags applied to vitals simulator resources."
  type        = map(string)
  default     = {}
}
