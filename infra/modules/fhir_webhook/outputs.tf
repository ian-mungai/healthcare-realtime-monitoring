output "lambda_function_name" {
  description = "Name of the FHIR webhook Lambda function."
  value       = aws_lambda_function.fhir_webhook.function_name
}

output "webhook_url" {
  description = "Permanent HAPI FHIR webhook URL."
  value       = "${var.api_endpoint}/webhooks/fhir"
}

output "health_url" {
  description = "Permanent FHIR webhook health endpoint."
  value       = "${var.api_endpoint}/health"
}
