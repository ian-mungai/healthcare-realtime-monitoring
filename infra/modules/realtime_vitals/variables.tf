variable "deletion_protection_enabled" {
  description = "Protect realtime DynamoDB tables from deletion."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to realtime vitals resources."
  type        = map(string)
  default     = {}
}
