data "aws_caller_identity" "current" {}

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

resource "aws_iam_role" "lambda" {
  name               = "healthcare_realtime_vitals_processor_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid    = "ReadVitalsKinesisStream"
    effect = "Allow"

    actions = [
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:ListShards"
    ]

    resources = [
      var.kinesis_stream_arn
    ]
  }

  statement {
    sid    = "ReadWebSocketConnections"
    effect = "Allow"

    actions = [
      "dynamodb:Scan",
      "dynamodb:DeleteItem"
    ]

    resources = [
      var.connections_table_arn
    ]
  }

  statement {
    sid    = "ManageWebSocketConnections"
    effect = "Allow"

    actions = [
      "execute-api:ManageConnections"
    ]

    resources = [
      "arn:aws:execute-api:us-east-1:${data.aws_caller_identity.current.account_id}:${var.websocket_api_id}/${var.websocket_stage_name}/POST/@connections",
      "arn:aws:execute-api:us-east-1:${data.aws_caller_identity.current.account_id}:${var.websocket_api_id}/${var.websocket_stage_name}/POST/@connections/*"
    ]
  }

  statement {
    sid    = "WriteLatestVitals"
    effect = "Allow"

    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
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
      "arn:aws:logs:us-east-1:*:*"
    ]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "healthcare_realtime_vitals_processor"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_lambda_function" "vitals_processor" {
  function_name = "healthcare_realtime_vitals_processor"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  timeout     = 30
  memory_size = 256

  environment {
    variables = {
      LATEST_VITALS_TABLE = var.latest_vitals_table_name
      CONNECTIONS_TABLE   = var.connections_table_name
      WEBSOCKET_ENDPOINT  = "https://${var.websocket_api_id}.execute-api.us-east-1.amazonaws.com/${var.websocket_stage_name}"
    }
  }

  tags = var.tags
}
resource "aws_lambda_event_source_mapping" "vitals_kinesis" {
  event_source_arn  = var.kinesis_stream_arn
  function_name     = aws_lambda_function.vitals_processor.arn
  starting_position = "LATEST"

  batch_size                         = 10
  maximum_batching_window_in_seconds = 0

  function_response_types = [
    "ReportBatchItemFailures"
  ]

  bisect_batch_on_function_error = true
  maximum_retry_attempts         = 3
  maximum_record_age_in_seconds  = 300
  enabled                        = true
}

