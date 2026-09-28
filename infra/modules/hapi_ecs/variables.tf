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

variable "data_classification" {
  description = "Data classification applied as the DataClassification tag on resources that hold data."
  type        = string
  validation {
    condition     = contains(["Public", "Synthetic", "Internal", "Confidential", "Restricted"], var.data_classification)
    error_message = "data_classification must be Public, Synthetic, Internal, Confidential or Restricted."
  }
}
