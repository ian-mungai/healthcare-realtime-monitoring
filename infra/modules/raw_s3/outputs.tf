output "bucket_name" {
  description = "Healthcare S3 bucket name"
  value       = aws_s3_bucket.raw.bucket
}

output "bucket_arn" {
  description = "Healthcare S3 bucket ARN"
  value       = aws_s3_bucket.raw.arn
}