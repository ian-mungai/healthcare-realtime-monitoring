variable "bucket_name" {
  description = "Name of the S3 bucket used for healthcare data"
  type        = string
}

variable "tags" {
  description = "Tags assigned to the S3 bucket"
  type        = map(string)
  default     = {}
}