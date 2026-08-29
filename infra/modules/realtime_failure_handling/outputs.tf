output "vitals_failures_queue_arn" {
  description = "ARN of the realtime vitals failure queue."
  value       = aws_sqs_queue.vitals_failures.arn
}

output "vitals_failures_queue_url" {
  description = "URL of the realtime vitals failure queue."
  value       = aws_sqs_queue.vitals_failures.url
}

output "vitals_failures_queue_name" {
  description = "Name of the realtime vitals failure queue."
  value       = aws_sqs_queue.vitals_failures.name
}