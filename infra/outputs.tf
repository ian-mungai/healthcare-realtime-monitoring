output "kinesis_stream_name" {
  description = "Kinesis stream used for realtime FHIR vital events"
  value       = module.kinesis.stream_name
}

output "kinesis_stream_arn" {
  description = "Kinesis stream ARN"
  value       = module.kinesis.stream_arn
}