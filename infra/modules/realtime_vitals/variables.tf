variable "deletion_protection_enabled" {
  description = "Protect realtime DynamoDB tables from deletion."
  type        = bool
  default     = true
}

variable "latest_vitals_table_name" {
  description = "Name of the latest-vitals DynamoDB table."
  type        = string
}

variable "processed_observations_table_name" {
  description = "Name of the realtime idempotency DynamoDB table."
  type        = string
}

variable "load_test_results_table_name" {
  description = "Name of the load-test results DynamoDB table."
  type        = string
}

variable "feature_window_table_name" {
  description = "DynamoDB table holding each encounter's feature-window readings for the early-warning endpoint."
  type        = string
}

variable "websocket_connections_table_name" {
  description = "Name of the active WebSocket connections DynamoDB table."
  type        = string
}

variable "tags" {
  description = "Tags applied to realtime vitals resources."
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

variable "connections_data_classification" {
  description = "Data classification for the WebSocket connections table, which stores caller IAM principal ARNs."
  type        = string
  validation {
    condition     = contains(["Public", "Synthetic", "Internal", "Confidential", "Restricted"], var.connections_data_classification)
    error_message = "connections_data_classification must be Public, Synthetic, Internal, Confidential or Restricted."
  }
}
