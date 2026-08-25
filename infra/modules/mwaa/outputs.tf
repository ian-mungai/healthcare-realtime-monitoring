output "environment_name" {
  value = aws_mwaa_environment.healthcare_realtime.name
}

output "environment_arn" {
  value = aws_mwaa_environment.healthcare_realtime.arn
}

output "execution_role_arn" {
  value = aws_iam_role.mwaa_execution.arn
}

output "source_bucket_name" {
  value = aws_s3_bucket.mwaa.bucket
}

output "webserver_url" {
  value = aws_mwaa_environment.healthcare_realtime.webserver_url
}