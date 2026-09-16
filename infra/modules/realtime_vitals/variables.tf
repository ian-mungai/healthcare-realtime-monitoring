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

variable "websocket_connections_table_name" {
  description = "Name of the active WebSocket connections DynamoDB table."
  type        = string
}

variable "tags" {
  description = "Tags applied to realtime vitals resources."
  type        = map(string)
  default     = {}
}
