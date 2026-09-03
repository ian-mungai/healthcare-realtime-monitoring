module "fhir_webhook" {
  source = "./modules/fhir_webhook"

  aws_region = var.aws_region

  api_id       = module.vitals_api.api_id
  api_endpoint = module.vitals_api.api_endpoint

  kinesis_stream_name = module.kinesis.stream_name
  kinesis_stream_arn  = module.kinesis.stream_arn

  lambda_zip_path   = "${path.root}/../build/lambda/fhir_webhook.zip"
  webhook_secret_id = "healthcare-realtime/fhir-webhook"

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

output "fhir_webhook_url" {
  description = "Permanent HAPI FHIR webhook URL."
  value       = module.fhir_webhook.webhook_url
}

output "fhir_webhook_health_url" {
  description = "Permanent FHIR webhook health endpoint."
  value       = module.fhir_webhook.health_url
}

output "fhir_webhook_lambda_name" {
  description = "FHIR webhook Lambda function name."
  value       = module.fhir_webhook.lambda_function_name
}
