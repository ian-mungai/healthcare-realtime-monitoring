variable "bucket_name" {
  description = "Name of the S3 bucket used for healthcare data"
  type        = string
}

variable "force_destroy" {
  description = "Allow Terraform to delete all object versions during an explicitly approved teardown."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags assigned to the S3 bucket"
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
