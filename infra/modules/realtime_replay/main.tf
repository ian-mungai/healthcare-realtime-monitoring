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
  name               = "healthcare_realtime_vitals_replay_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid    = "ReadAndReplayVitalsKinesisRecords"
    effect = "Allow"

    actions = [
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "kinesis:PutRecords"
    ]

    resources = [
      var.kinesis_stream_arn
    ]
  }

  statement {
    sid    = "ReadRealtimeFailureQueue"
    effect = "Allow"

    actions = [
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage"
    ]

    resources = [
      var.failure_queue_arn
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
  name   = "healthcare_realtime_vitals_replay"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_lambda_function" "vitals_replay" {
  function_name = "healthcare_realtime_vitals_replay"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  timeout     = 30
  memory_size = 256

  environment {
    variables = {
      KINESIS_STREAM_ARN  = var.kinesis_stream_arn
      MAX_REPLAY_ATTEMPTS = "1"
    }
  }

  tags = var.tags
}

resource "aws_lambda_event_source_mapping" "failure_queue" {
  event_source_arn = var.failure_queue_arn
  function_name    = aws_lambda_function.vitals_replay.arn

  batch_size                         = 10
  maximum_batching_window_in_seconds = 0

  function_response_types = [
    "ReportBatchItemFailures"
  ]

  enabled = true
}
