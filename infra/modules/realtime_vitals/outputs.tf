output "latest_vitals_table_name" {
  description = "DynamoDB table containing the latest patient vital state."
  value       = aws_dynamodb_table.latest_vitals.name
}

output "latest_vitals_table_arn" {
  description = "ARN of the DynamoDB latest vitals table."
  value       = aws_dynamodb_table.latest_vitals.arn
}

output "processed_observations_table_name" {
  description = "DynamoDB table containing realtime observation idempotency claims."
  value       = aws_dynamodb_table.processed_observations.name
}

output "processed_observations_table_arn" {
  description = "ARN of the realtime observation idempotency table."
  value       = aws_dynamodb_table.processed_observations.arn
}

output "load_test_results_table_name" {
  description = "DynamoDB table containing isolated load-test observations."
  value       = aws_dynamodb_table.load_test_results.name
}

output "load_test_results_table_arn" {
  description = "ARN of the isolated load-test results table."
  value       = aws_dynamodb_table.load_test_results.arn
}

output "websocket_connections_table_name" {
  description = "DynamoDB table containing active WebSocket connection IDs."
  value       = aws_dynamodb_table.websocket_connections.name
}

output "websocket_connections_table_arn" {
  description = "ARN of the WebSocket connections DynamoDB table."
  value       = aws_dynamodb_table.websocket_connections.arn
}
