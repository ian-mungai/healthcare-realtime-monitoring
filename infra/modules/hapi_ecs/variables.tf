variable "vpc_id" {
  description = "VPC containing the HAPI FHIR infrastructure."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs used by the HAPI Application Load Balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnet IDs used by HAPI ECS tasks and PostgreSQL."
  type        = list(string)
}

variable "deletion_protection" {
  description = "Protect the HAPI RDS instance from deletion."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip the HAPI RDS final snapshot when deletion is enabled."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to HAPI FHIR resources."
  type        = map(string)
  default     = {}
}
