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

variable "allowed_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the HAPI load balancer: the NAT gateway address and approved operator addresses."
  type        = list(string)
  validation {
    condition     = length(var.allowed_ingress_cidrs) > 0 && alltrue([for cidr in var.allowed_ingress_cidrs : can(cidrhost(cidr, 0)) && cidr != "0.0.0.0/0"])
    error_message = "allowed_ingress_cidrs must list valid CIDR blocks and must not open the load balancer to 0.0.0.0/0."
  }
}
