output "lambda_function_name" {
  description = "Name of the realtime vitals replay Lambda function."
  value       = aws_lambda_function.vitals_replay.function_name
}

output "lambda_function_arn" {
  description = "ARN of the realtime vitals replay Lambda function."
  value       = aws_lambda_function.vitals_replay.arn
}

output "lambda_role_arn" {
  description = "ARN of the realtime vitals replay Lambda execution role."
  value       = aws_iam_role.lambda.arn
}

output "event_source_mapping_uuid" {
  description = "UUID of the SQS replay event source mapping."
  value       = aws_lambda_event_source_mapping.failure_queue.uuid
}
