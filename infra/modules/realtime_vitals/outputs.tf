output "latest_vitals_table_name" {
  description = "DynamoDB table containing the latest patient vital state."
  value       = aws_dynamodb_table.latest_vitals.name
}

output "latest_vitals_table_arn" {
  description = "ARN of the DynamoDB latest vitals table."
  value       = aws_dynamodb_table.latest_vitals.arn
}

output "websocket_connections_table_name" {
  description = "DynamoDB table containing active WebSocket connection IDs."
  value       = aws_dynamodb_table.websocket_connections.name
}

output "websocket_connections_table_arn" {
  description = "ARN of the WebSocket connections DynamoDB table."
  value       = aws_dynamodb_table.websocket_connections.arn
}