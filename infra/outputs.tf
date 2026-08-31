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

output "data_jobs_ecs_cluster_arn" {
  description = "ARN of the shared ECS cluster for data processing jobs."
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

output "soda_ecr_repository_url" {
  description = "ECR repository containing the Soda image."
  value       = module.soda_ecs.ecr_repository_url
}

output "soda_ecs_task_definition_arn" {
  description = "Soda ECS task definition ARN."
  value       = module.soda_ecs.task_definition_arn
}

output "soda_ecs_task_role_arn" {
  description = "Soda ECS task role ARN."
  value       = module.soda_ecs.task_role_arn
}

output "soda_ecs_task_execution_role_arn" {
  description = "Soda ECS task execution role ARN."
  value       = module.soda_ecs.task_execution_role_arn
}

output "soda_ecs_security_group_id" {
  description = "Security group used by Soda ECS tasks."
  value       = module.soda_ecs.security_group_id
}

output "cloudwatch_dashboard_name" {
  description = "CloudWatch operational dashboard."
  value       = module.observability.dashboard_name
}

output "pipeline_failure_alarm_name" {
  description = "Pipeline task failure CloudWatch alarm."
  value       = module.observability.pipeline_failure_alarm_name
}

output "mwaa_queue_age_alarm_name" {
  description = "MWAA native queue age CloudWatch alarm."
  value       = module.observability.mwaa_queue_age_alarm_name
}

output "latest_vitals_table_name" {
  description = "DynamoDB latest vitals table name."
  value       = module.realtime_vitals.latest_vitals_table_name
}

output "latest_vitals_table_arn" {
  description = "DynamoDB latest vitals table ARN."
  value       = module.realtime_vitals.latest_vitals_table_arn
}

output "realtime_processor_lambda_name" {
  description = "Realtime vitals processor Lambda function name."
  value       = module.realtime_processor.lambda_function_name
}

output "realtime_processor_lambda_arn" {
  description = "Realtime vitals processor Lambda function ARN."
  value       = module.realtime_processor.lambda_function_arn
}

output "websocket_connections_table_name" {
  description = "WebSocket connections table name."
  value       = module.realtime_vitals.websocket_connections_table_name
}

output "websocket_connections_table_arn" {
  description = "WebSocket connections table ARN."
  value       = module.realtime_vitals.websocket_connections_table_arn
}

output "realtime_websocket_url" {
  description = "Realtime vitals WebSocket URL."
  value       = module.realtime_websocket.websocket_url
}

output "realtime_websocket_api_id" {
  description = "Realtime vitals WebSocket API ID."
  value       = module.realtime_websocket.api_id
}

output "live_processing_latency_alarm_name" {
  description = "Live processing latency CloudWatch alarm."
  value       = module.observability.live_processing_latency_alarm_name
}

output "websocket_delivery_failure_alarm_name" {
  description = "WebSocket delivery failure CloudWatch alarm."
  value       = module.observability.websocket_delivery_failure_alarm_name
}

output "vitals_api_endpoint" {
  description = "Base URL of the latest-vitals HTTP API."
  value       = module.vitals_api.api_endpoint
}

output "vitals_api_id" {
  description = "ID of the latest-vitals HTTP API."
  value       = module.vitals_api.api_id
}

output "realtime_observability_dashboard_name" {
  description = "Name of the realtime CloudWatch observability dashboard."
  value       = module.realtime_observability.dashboard_name
}

output "realtime_processing_latency_alarm_name" {
  description = "Name of the realtime processing latency alarm."
  value       = module.realtime_observability.processing_latency_alarm_name
}

output "realtime_websocket_delivery_failure_alarm_name" {
  description = "Name of the realtime WebSocket delivery failure alarm."
  value       = module.realtime_observability.websocket_delivery_failure_alarm_name
}

output "realtime_processor_error_alarm_name" {
  description = "Name of the realtime processor error alarm."
  value       = module.realtime_observability.processor_error_alarm_name
}

output "realtime_processor_throttle_alarm_name" {
  description = "Name of the realtime processor throttle alarm."
  value       = module.realtime_observability.processor_throttle_alarm_name
}

output "realtime_iterator_age_alarm_name" {
  description = "Name of the realtime Kinesis consumer iterator-age alarm."
  value       = module.realtime_observability.iterator_age_alarm_name
}

output "realtime_alert_topic_arn" {
  description = "ARN of the realtime CloudWatch alarm SNS topic."
  value       = module.realtime_observability.alert_topic_arn
}

output "realtime_alert_topic_name" {
  description = "Name of the realtime CloudWatch alarm SNS topic."
  value       = module.realtime_observability.alert_topic_name
}

output "hapi_fhir_base_url" {
  description = "Public HAPI FHIR R4 base URL."
  value       = module.hapi_ecs.fhir_base_url
}

output "hapi_ecs_cluster_name" {
  description = "ECS cluster hosting persistent realtime services."
  value       = module.hapi_ecs.cluster_name
}

output "hapi_ecs_service_name" {
  description = "HAPI FHIR ECS service name."
  value       = module.hapi_ecs.service_name
}

output "hapi_database_endpoint" {
  description = "Private PostgreSQL endpoint backing HAPI FHIR."
  value       = module.hapi_ecs.database_endpoint
}

output "vitals_simulator_ecr_repository_name" {
  description = "Name of the vitals simulator ECR repository."
  value       = module.vitals_simulator_ecs.ecr_repository_name
}

output "vitals_simulator_ecr_repository_url" {
  description = "URL of the vitals simulator ECR repository."
  value       = module.vitals_simulator_ecs.ecr_repository_url
}

output "vitals_simulator_ecr_repository_arn" {
  description = "ARN of the vitals simulator ECR repository."
  value       = module.vitals_simulator_ecs.ecr_repository_arn
}

output "vitals_simulator_task_definition_arn" {
  description = "ARN of the vitals simulator ECS task definition."
  value       = module.vitals_simulator_ecs.task_definition_arn
}

output "vitals_simulator_task_definition_family" {
  description = "Family of the vitals simulator ECS task definition."
  value       = module.vitals_simulator_ecs.task_definition_family
}

output "vitals_simulator_task_execution_role_arn" {
  description = "ARN of the vitals simulator ECS task execution role."
  value       = module.vitals_simulator_ecs.task_execution_role_arn
}

output "vitals_simulator_task_role_arn" {
  description = "ARN of the vitals simulator ECS task role."
  value       = module.vitals_simulator_ecs.task_role_arn
}

output "vitals_simulator_security_group_id" {
  description = "Security group used by vitals simulator ECS tasks."
  value       = module.vitals_simulator_ecs.security_group_id
}

output "vitals_simulator_log_group_name" {
  description = "CloudWatch log group used by vitals simulator ECS tasks."
  value       = module.vitals_simulator_ecs.log_group_name
}
