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

output "quarantine_table_name" {
  description = "Glue Catalog table exposing quarantined FHIR observations."
  value       = aws_glue_catalog_table.quarantined_fhir_observations.name
}

output "table_optimizer_types" {
  description = "Glue managed Iceberg optimizers enabled on the processed table."
  value = concat(
    aws_glue_catalog_table_optimizer.compaction[*].type,
    aws_glue_catalog_table_optimizer.retention[*].type,
    aws_glue_catalog_table_optimizer.orphan_file_deletion[*].type,
  )
}
