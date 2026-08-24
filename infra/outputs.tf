output "kinesis_stream_name" {
  description = "Kinesis stream used for realtime FHIR vital events"
  value       = module.kinesis.stream_name
}

output "kinesis_stream_arn" {
  description = "Kinesis stream ARN"
  value       = module.kinesis.stream_arn
}

output "raw_s3_bucket_name" {
  description = "S3 bucket used for healthcare realtime data"
  value       = module.raw_s3.bucket_name
}

output "raw_s3_bucket_arn" {
  description = "Healthcare S3 bucket ARN"
  value       = module.raw_s3.bucket_arn
}

output "firehose_delivery_stream_name" {
  description = "Firehose stream delivering realtime vitals to S3"
  value       = module.firehose.delivery_stream_name
}

output "firehose_delivery_stream_arn" {
  description = "Firehose delivery stream ARN"
  value       = module.firehose.delivery_stream_arn
}