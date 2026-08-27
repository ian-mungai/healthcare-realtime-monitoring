data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type = "Service"

      identifiers = [
        "lambda.amazonaws.com"
      ]
    }

    actions = [
      "sts:AssumeRole"
    ]
  }
}

resource "aws_iam_role" "websocket_lambda" {
  name               = "healthcare_realtime_websocket_handler_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "websocket_lambda" {
  statement {
    sid    = "ManageWebSocketConnections"
    effect = "Allow"

    actions = [
      "dynamodb:PutItem",
      "dynamodb:DeleteItem"
    ]

    resources = [
      var.connections_table_arn
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
      "arn:aws:logs:us-east-1:*:*"
    ]
  }
}

resource "aws_iam_role_policy" "websocket_lambda" {
  name   = "healthcare_realtime_websocket_handler"
  role   = aws_iam_role.websocket_lambda.id
  policy = data.aws_iam_policy_document.websocket_lambda.json
}

resource "aws_lambda_function" "websocket_handler" {
  function_name = "healthcare_realtime_websocket_handler"
  role          = aws_iam_role.websocket_lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  timeout     = 10
  memory_size = 128

  environment {
    variables = {
      CONNECTIONS_TABLE = var.connections_table_name
    }
  }

  tags = var.tags
}

resource "aws_apigatewayv2_api" "vitals_websocket" {
  name                       = "healthcare-realtime-vitals-websocket"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "websocket_handler" {
  api_id             = aws_apigatewayv2_api.vitals_websocket.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.websocket_handler.invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.vitals_websocket.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.websocket_handler.id}"
}

resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.vitals_websocket.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.websocket_handler.id}"
}

resource "aws_lambda_permission" "websocket" {
  statement_id  = "AllowWebSocketApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.websocket_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.vitals_websocket.execution_arn}/*"
}

resource "aws_apigatewayv2_stage" "development" {
  api_id      = aws_apigatewayv2_api.vitals_websocket.id
  name        = "development"
  auto_deploy = true
}