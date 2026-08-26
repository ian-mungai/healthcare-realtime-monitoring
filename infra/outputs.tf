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

output "glue_job_name" {
  description = "Glue raw-to-processed job"
  value       = module.glue.job_name
}

output "glue_database_name" {
  description = "Glue Data Catalog database"
  value       = module.glue.database_name
}

output "glue_role_arn" {
  description = "Glue service role ARN"
  value       = module.glue.role_arn
}

output "mwaa_environment_name" {
  value = module.mwaa.environment_name
}

output "mwaa_environment_arn" {
  value = module.mwaa.environment_arn
}

output "mwaa_execution_role_arn" {
  value = module.mwaa.execution_role_arn
}

output "mwaa_source_bucket_name" {
  value = module.mwaa.source_bucket_name
}

output "mwaa_webserver_url" {
  value = module.mwaa.webserver_url
}
output "dbt_ecr_repository_url" {
  description = "ECR repository containing the dbt image."
  value       = module.dbt_ecs.ecr_repository_url
}

output "dbt_ecs_cluster_name" {
  description = "ECS cluster running dbt."
  value       = module.dbt_ecs.cluster_name
}

output "dbt_ecs_cluster_arn" {
  description = "ECS cluster ARN."
  value       = module.dbt_ecs.cluster_arn
}

output "dbt_ecs_task_definition_arn" {
  description = "dbt ECS task definition ARN."
  value       = module.dbt_ecs.task_definition_arn
}

output "dbt_ecs_task_role_arn" {
  description = "dbt ECS task role ARN."
  value       = module.dbt_ecs.task_role_arn
}

output "dbt_ecs_task_execution_role_arn" {
  description = "dbt ECS task execution role ARN."
  value       = module.dbt_ecs.task_execution_role_arn
}

output "dbt_ecs_security_group_id" {
  description = "Security group used by dbt ECS tasks."
  value       = module.dbt_ecs.security_group_id
}
