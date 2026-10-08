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
      LATEST_VITALS_TABLE   = var.latest_vitals_table_name
      PATIENT_ACCESS_POLICY = var.patient_access_policy
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

# GET /patients/{patient_id}/early-warning (services/early_warning): NEWS2 from the latest cache and the approved
# model's score of the current encounter's feature window, stored once beside the window readings.
resource "aws_iam_role" "early_warning" {
  name               = "healthcare_realtime_early_warning_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "early_warning" {
  statement {
    sid       = "ReadLatestVitals"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem"]
    resources = [var.latest_vitals_table_arn]
  }

  statement {
    sid       = "ReadWindowAndStoreScore"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"]
    resources = [var.feature_window_table_arn]
  }

  statement {
    sid       = "ReadScoringParameters"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.data_bucket_name}/ml/model_artifacts/*/scoring_parameters.json"]
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

resource "aws_iam_role_policy" "early_warning" {
  name   = "healthcare_realtime_early_warning"
  role   = aws_iam_role.early_warning.id
  policy = data.aws_iam_policy_document.early_warning.json
}

resource "aws_lambda_function" "early_warning" {
  function_name = "healthcare_realtime_early_warning"

  role    = aws_iam_role.early_warning.arn
  runtime = "python3.12"
  handler = "handler.lambda_handler"

  filename         = var.early_warning_zip_path
  source_code_hash = filebase64sha256(var.early_warning_zip_path)

  timeout     = 15
  memory_size = 256

  environment {
    variables = {
      LATEST_VITALS_TABLE       = var.latest_vitals_table_name
      FEATURE_WINDOW_TABLE      = var.feature_window_table_name
      DATA_BUCKET_NAME          = var.data_bucket_name
      ML_APPROVED_MODEL_VERSION = var.approved_model_version
      PATIENT_ACCESS_POLICY     = var.patient_access_policy
    }
  }

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "early_warning" {
  api_id = aws_apigatewayv2_api.vitals_api.id

  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.early_warning.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "early_warning" {
  api_id = aws_apigatewayv2_api.vitals_api.id

  route_key          = "GET /patients/{patient_id}/early-warning"
  authorization_type = "AWS_IAM"
  target             = "integrations/${aws_apigatewayv2_integration.early_warning.id}"
}

resource "aws_lambda_permission" "early_warning" {
  statement_id = "AllowApiGatewayInvoke"

  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.early_warning.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_apigatewayv2_api.vitals_api.execution_arn}/*/*"
}

resource "aws_apigatewayv2_stage" "development" {
  api_id = aws_apigatewayv2_api.vitals_api.id
  name   = var.stage_name

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
