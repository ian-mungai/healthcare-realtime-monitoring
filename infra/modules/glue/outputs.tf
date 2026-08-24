output "job_name" {
  description = "Glue raw-to-processed job name"
  value       = aws_glue_job.raw_to_processed.name
}

output "database_name" {
  description = "Glue Data Catalog database name"
  value       = aws_glue_catalog_database.healthcare_realtime.name
}

output "role_arn" {
  description = "Glue service role ARN"
  value       = aws_iam_role.glue.arn
}