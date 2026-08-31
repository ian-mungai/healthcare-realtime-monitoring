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

variable "tags" {
  description = "Tags applied to HAPI FHIR resources."
  type        = map(string)
  default     = {}
}