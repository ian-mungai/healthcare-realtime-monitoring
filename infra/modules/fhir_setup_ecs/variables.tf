variable "aws_region" {
  description = "AWS region of the deployment."
  type        = string
}

variable "vpc_id" {
  description = "VPC whose private subnets run the task."
  type        = string
}

variable "fhir_base_url" {
  description = "HAPI FHIR base URL, reached through the NAT gateway."
  type        = string
}

variable "data_bucket_name" {
  description = "Healthcare data bucket holding the seed bundles and the resource map."
  type        = string
}

variable "resource_map_s3_key" {
  description = "S3 key of the published HAPI resource map."
  type        = string
}

variable "seed_bundles_s3_prefix" {
  description = "S3 prefix, without a trailing slash, where the Synthea bundles are uploaded."
  type        = string
  default     = "seed/synthea/fhir"
}

variable "webhook_secret_id" {
  description = "Secrets Manager identifier of the FHIR webhook secret."
  type        = string
}

variable "image_repository_url" {
  description = "ECR repository URL of the vitals simulator image."
  type        = string
}

variable "image_repository_arn" {
  description = "ECR repository ARN of the vitals simulator image."
  type        = string
}

variable "image_tag" {
  description = "Immutable vitals simulator image tag."
  type        = string
}

variable "tags" {
  description = "Tags applied to FHIR setup resources."
  type        = map(string)
  default     = {}
}
