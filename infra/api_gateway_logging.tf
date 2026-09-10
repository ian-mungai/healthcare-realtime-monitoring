data "aws_iam_policy_document" "api_gateway_cloudwatch_assume_role" {
  statement {
    effect = "Allow"

    actions = [
      "sts:AssumeRole"
    ]

    principals {
      type = "Service"

      identifiers = [
        "apigateway.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role" "api_gateway_cloudwatch" {
  name               = "healthcare_realtime_api_gateway_cloudwatch_role"
  assume_role_policy = data.aws_iam_policy_document.api_gateway_cloudwatch_assume_role.json

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = "development"
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  role       = aws_iam_role.api_gateway_cloudwatch.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "cloudwatch" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch.arn

  depends_on = [aws_iam_role_policy_attachment.api_gateway_cloudwatch]
}
