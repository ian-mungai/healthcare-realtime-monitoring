variable "stream_name" {
  description = "Name of the Kinesis Data Stream used for FHIR vital sign events"
  type        = string
}

variable "retention_period_hours" {
  description = "Number of hours records are retained in Kinesis"
  type        = number
  default     = 24
}

variable "stream_mode" {
  description = "Kinesis stream capacity mode"
  type        = string
  default     = "ON_DEMAND"

  validation {
    condition     = contains(["ON_DEMAND", "PROVISIONED"], var.stream_mode)
    error_message = "stream_mode must be ON_DEMAND or PROVISIONED"
  }
}

variable "tags" {
  description = "Tags assigned to the Kinesis stream"
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
