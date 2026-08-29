variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "tags" {
  description = "Tags applied to realtime failure-handling resources."
  type        = map(string)
}