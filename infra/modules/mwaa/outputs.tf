output "workflow_name" {
  value = awscc_mwaaserverless_workflow.healthcare_realtime.name
}

output "workflow_arn" {
  value = awscc_mwaaserverless_workflow.healthcare_realtime.workflow_arn
}

output "workflow_status" {
  value = awscc_mwaaserverless_workflow.healthcare_realtime.workflow_status
}

output "workflow_version" {
  value = awscc_mwaaserverless_workflow.healthcare_realtime.workflow_version
}

output "execution_role_arn" {
  value = aws_iam_role.mwaa_execution.arn
}

output "source_bucket_name" {
  value = aws_s3_bucket.mwaa.bucket
}

output "task_failure_alarm_name" {
  description = "CloudWatch alarm raised when an MWAA Serverless task fails."
  value       = aws_cloudwatch_metric_alarm.task_failures.alarm_name
}
