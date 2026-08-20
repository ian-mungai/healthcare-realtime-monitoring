output "stream_name" {
  description = "Kinesis stream name"
  value       = aws_kinesis_stream.vitals_events.name
}

output "stream_arn" {
  description = "Kinesis stream ARN"
  value       = aws_kinesis_stream.vitals_events.arn
}