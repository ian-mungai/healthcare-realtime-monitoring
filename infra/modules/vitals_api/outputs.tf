output "api_id" {
  description = "ID of the vitals HTTP API."
  value       = aws_apigatewayv2_api.vitals_api.id
}

output "api_endpoint" {
  description = "Base endpoint for the vitals HTTP API."
  value       = aws_apigatewayv2_stage.development.invoke_url
}

output "lambda_function_name" {
  description = "Name of the vitals API Lambda function."
  value       = aws_lambda_function.vitals_api.function_name
}

output "lambda_role_arn" {
  description = "ARN of the vitals API Lambda execution role."
  value       = aws_iam_role.vitals_api.arn
}

