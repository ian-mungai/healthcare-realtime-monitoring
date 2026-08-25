variable "name" {
  description = "Name prefix for network resources"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "tags" {
  description = "Tags applied to network resources"
  type        = map(string)
  default     = {}
}