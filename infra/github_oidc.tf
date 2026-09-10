resource "aws_iam_openid_connect_provider" "github" {
  count = var.enable_github_oidc ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = var.github_deployment_environment
    ManagedBy   = "terraform"
  }
}

locals {
  github_oidc_subject_prefix = var.github_oidc_subject_prefix != "" ? var.github_oidc_subject_prefix : "repo:${var.github_repository}"
}

data "aws_iam_policy_document" "github_deployment_assume_role" {
  count = var.enable_github_oidc ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.github_oidc_subject_prefix}:environment:${var.github_deployment_environment}"]
    }
  }
}

resource "aws_iam_role" "github_deployment" {
  count = var.enable_github_oidc ? 1 : 0

  name                 = "healthcare_realtime_github_deployment"
  assume_role_policy   = data.aws_iam_policy_document.github_deployment_assume_role[0].json
  max_session_duration = 3600

  tags = {
    Project     = "healthcare_realtime_monitoring"
    Environment = var.github_deployment_environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "github_deployment" {
  for_each = var.enable_github_oidc ? toset(var.github_deployment_policy_arns) : toset([])

  role       = aws_iam_role.github_deployment[0].name
  policy_arn = each.value
}
