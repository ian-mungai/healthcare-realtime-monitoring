output "delivery_stream_name" {
  description = "Firehose delivery stream name"
  value       = aws_kinesis_firehose_delivery_stream.vitals.name
}

output "delivery_stream_arn" {
  description = "Firehose delivery stream ARN"
  value       = aws_kinesis_firehose_delivery_stream.vitals.arn
}

output "role_arn" {
  description = "IAM role used by Firehose"
  value       = aws_iam_role.firehose.arn
}