data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect = "Allow"

    actions = [
      "sts:AssumeRole"
    ]

    principals {
      type = "Service"

      identifiers = [
        "lambda.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role" "fhir_webhook" {
  name               = "healthcare_realtime_fhir_webhook_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "fhir_webhook" {
  statement {
    sid    = "PublishVitalsToKinesis"
    effect = "Allow"

    actions = [
      "kinesis:PutRecord"
    ]

    resources = [
      var.kinesis_stream_arn
    ]
  }

  statement {
    sid    = "WriteLambdaLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]

    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
    ]
  }
}

resource "aws_iam_role_policy" "fhir_webhook" {
  name   = "healthcare_realtime_fhir_webhook"
  role   = aws_iam_role.fhir_webhook.id
  policy = data.aws_iam_policy_document.fhir_webhook.json
}

resource "aws_lambda_function" "fhir_webhook" {
  function_name = "healthcare_realtime_fhir_webhook"

  role    = aws_iam_role.fhir_webhook.arn
  runtime = "python3.12"
  handler = "services.fhir_webhook.app.lambda_handler.lambda_handler"

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  timeout     = 10
  memory_size = 256

  environment {
    variables = {
      FHIR_WEBHOOK_SECRET = var.webhook_secret
      KINESIS_STREAM_NAME = var.kinesis_stream_name
    }
  }

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "fhir_webhook" {
  api_id = var.api_id

  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fhir_webhook.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "fhir_webhook" {
  api_id = var.api_id

  route_key          = "POST /webhooks/fhir"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.fhir_webhook.id}"
}

resource "aws_apigatewayv2_route" "fhir_webhook_get" {
  api_id = var.api_id

  route_key          = "GET /webhooks/fhir"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.fhir_webhook.id}"
}

resource "aws_apigatewayv2_route" "fhir_webhook_head" {
  api_id = var.api_id

  route_key          = "HEAD /webhooks/fhir"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.fhir_webhook.id}"
}

resource "aws_apigatewayv2_route" "fhir_webhook_metadata" {
  api_id = var.api_id

  route_key          = "GET /webhooks/fhir/metadata"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.fhir_webhook.id}"
}

resource "aws_apigatewayv2_route" "fhir_webhook_update" {
  api_id = var.api_id

  route_key          = "PUT /webhooks/fhir/{resource_type}/{resource_id}"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.fhir_webhook.id}"
}

resource "aws_apigatewayv2_route" "fhir_webhook_health" {
  api_id = var.api_id

  route_key          = "GET /health"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.fhir_webhook.id}"
}

resource "aws_lambda_permission" "fhir_webhook" {
  statement_id = "AllowApiGatewayFHIRWebhookInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fhir_webhook.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "arn:${data.aws_partition.current.partition}:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.api_id}/*/POST/webhooks/fhir"
}

resource "aws_lambda_permission" "fhir_webhook_get" {
  statement_id = "AllowApiGatewayFHIRWebhookGetInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fhir_webhook.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "arn:${data.aws_partition.current.partition}:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.api_id}/*/GET/webhooks/fhir"
}

resource "aws_lambda_permission" "fhir_webhook_head" {
  statement_id = "AllowApiGatewayFHIRWebhookHeadInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fhir_webhook.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "arn:${data.aws_partition.current.partition}:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.api_id}/*/HEAD/webhooks/fhir"
}

resource "aws_lambda_permission" "fhir_webhook_health" {
  statement_id = "AllowApiGatewayFHIRWebhookHealthInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fhir_webhook.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "arn:${data.aws_partition.current.partition}:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.api_id}/*/GET/health"
}

resource "aws_lambda_permission" "fhir_webhook_metadata" {
  statement_id = "AllowApiGatewayFHIRWebhookMetadataInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fhir_webhook.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "arn:${data.aws_partition.current.partition}:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.api_id}/*/GET/webhooks/fhir/metadata"
}

resource "aws_lambda_permission" "fhir_webhook_update" {
  statement_id = "AllowApiGatewayFHIRWebhookUpdateInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fhir_webhook.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "arn:${data.aws_partition.current.partition}:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.api_id}/*/PUT/webhooks/fhir/*"
}