output "api_id" {
  description = "API Gateway WebSocket API ID."
  value       = aws_apigatewayv2_api.vitals_websocket.id
}

output "websocket_url" {
  description = "Development WebSocket URL."
  value       = aws_apigatewayv2_stage.development.invoke_url
}

output "lambda_function_name" {
  description = "WebSocket connection handler Lambda function name."
  value       = aws_lambda_function.websocket_handler.function_name
}

output "lambda_execution_role_arn" {
  description = "WebSocket connection handler Lambda execution role ARN."
  value       = aws_iam_role.websocket_lambda.arn
}