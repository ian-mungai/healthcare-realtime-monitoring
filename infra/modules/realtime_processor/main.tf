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
    sid    = "SendFailedInvocationsToSqs"
    effect = "Allow"

    actions = [
      "sqs:SendMessage"
    ]

    resources = [
      var.failure_queue_arn
    ]
  }

  statement {
    sid    = "PublishLivePipelineMetrics"
    effect = "Allow"

    actions = [
      "cloudwatch:PutMetricData"
    ]

    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"

      values = [
        "HealthcareRealtime/Live"
      ]
    }
  }

  statement {
    sid    = "ManageWebSocketConnections"
    effect = "Allow"

    actions = [
      "dynamodb:DeleteItem",
      "dynamodb:Query"
    ]

    resources = [
      var.connections_table_arn,
      "${var.connections_table_arn}/index/patient_id-index"
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
      "arn:aws:logs:${var.aws_region}:*:*"
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
      WEBSOCKET_ENDPOINT  = "https://${var.websocket_api_id}.execute-api.${var.aws_region}.amazonaws.com/${var.websocket_stage_name}"
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
  parallelization_factor             = 3

  function_response_types = [
    "ReportBatchItemFailures"
  ]

  destination_config {
    on_failure {
      destination_arn = var.failure_queue_arn
    }
  }

  bisect_batch_on_function_error = true
  maximum_retry_attempts         = 3
  maximum_record_age_in_seconds  = 3600
  enabled                        = true
}