output "lambda_function_name" {
  description = "Realtime vitals processor Lambda function name."
  value       = aws_lambda_function.vitals_processor.function_name
}

output "lambda_function_arn" {
  description = "Realtime vitals processor Lambda function ARN."
  value       = aws_lambda_function.vitals_processor.arn
}

output "lambda_execution_role_arn" {
  description = "Realtime vitals processor Lambda execution role ARN."
  value       = aws_iam_role.lambda.arn
}