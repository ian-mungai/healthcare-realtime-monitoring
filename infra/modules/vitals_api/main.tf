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

resource "aws_iam_role" "vitals_api" {
  name               = "healthcare_realtime_vitals_api_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "vitals_api" {
  statement {
    sid    = "ReadLatestVitals"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem"
    ]

    resources = [
      var.latest_vitals_table_arn
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
      "arn:aws:logs:${var.aws_region}:*:*"
    ]
  }
}

resource "aws_iam_role_policy" "vitals_api" {
  name   = "healthcare_realtime_vitals_api"
  role   = aws_iam_role.vitals_api.id
  policy = data.aws_iam_policy_document.vitals_api.json
}

resource "aws_lambda_function" "vitals_api" {
  function_name = "healthcare_realtime_vitals_api"

  role    = aws_iam_role.vitals_api.arn
  runtime = "python3.12"
  handler = "handler.lambda_handler"

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  timeout     = 10
  memory_size = 256

  environment {
    variables = {
      LATEST_VITALS_TABLE = var.latest_vitals_table_name
    }
  }

  tags = var.tags
}

resource "aws_apigatewayv2_api" "vitals_api" {
  name          = "healthcare-realtime-vitals-api"
  protocol_type = "HTTP"

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "vitals_api_access" {
  name              = "/aws/apigateway/healthcare-realtime-vitals-api"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "vitals_api" {
  api_id = aws_apigatewayv2_api.vitals_api.id

  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.vitals_api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "latest_vitals" {
  api_id = aws_apigatewayv2_api.vitals_api.id

  route_key          = "GET /patients/{patient_id}/vitals"
  authorization_type = "AWS_IAM"
  target             = "integrations/${aws_apigatewayv2_integration.vitals_api.id}"
}

resource "aws_apigatewayv2_stage" "development" {
  api_id = aws_apigatewayv2_api.vitals_api.id
  name   = "development"

  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.vitals_api_access.arn
    format = jsonencode({
      requestId               = "$context.requestId"
      sourceIp                = "$context.identity.sourceIp"
      requestTime             = "$context.requestTime"
      protocol                = "$context.protocol"
      httpMethod              = "$context.httpMethod"
      routeKey                = "$context.routeKey"
      status                  = "$context.status"
      responseLength          = "$context.responseLength"
      integrationErrorMessage = "$context.integrationErrorMessage"
    })
  }

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id = "AllowApiGatewayInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.vitals_api.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_apigatewayv2_api.vitals_api.execution_arn}/*/*"
}
