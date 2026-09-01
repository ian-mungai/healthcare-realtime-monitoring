data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_s3_bucket" "mwaa" {
  bucket = var.source_bucket_name

  tags = var.tags
}

resource "aws_s3_bucket_versioning" "mwaa" {
  bucket = aws_s3_bucket.mwaa.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "mwaa" {
  bucket = aws_s3_bucket.mwaa.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

locals {
  workflow_definition = templatefile("${path.root}/../airflow/serverless/healthcare_realtime_pipeline.yml.tftpl", {
    glue_job_name                = var.glue_job_name
    glue_database_name           = var.glue_database_name
    glue_table_name              = var.glue_table_name
    dbt_ecs_task_definition_arn  = var.dbt_ecs_task_definition_arn
    dbt_ecs_security_group_id    = var.dbt_ecs_security_group_id
    dbt_ecs_subnet_ids           = var.dbt_ecs_subnet_ids
    soda_ecs_task_definition_arn = var.soda_ecs_task_definition_arn
    soda_ecs_security_group_id   = var.soda_ecs_security_group_id
    soda_ecs_subnet_ids          = var.soda_ecs_subnet_ids
  })
}

resource "aws_s3_object" "workflow_definition" {
  bucket       = aws_s3_bucket.mwaa.id
  key          = "workflows/healthcare_realtime_pipeline.yml"
  content      = local.workflow_definition
  content_type = "application/x-yaml"

  depends_on = [
    aws_s3_bucket_versioning.mwaa,
    aws_s3_bucket_public_access_block.mwaa,
  ]
}

data "aws_iam_policy_document" "mwaa_serverless_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type = "Service"

      identifiers = [
        "airflow-serverless.amazonaws.com"
      ]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "mwaa_execution" {
  name               = "healthcare_realtime_mwaa_serverless_execution_role"
  assume_role_policy = data.aws_iam_policy_document.mwaa_serverless_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "mwaa_s3_access" {
  statement {
    sid    = "ReadWorkflowDefinition"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]

    resources = [
      "${aws_s3_bucket.mwaa.arn}/workflows/*"
    ]
  }

  statement {
    sid    = "ReadHealthcareDataBucket"
    effect = "Allow"

    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}"
    ]
  }

  statement {
    sid    = "ReadHealthcareDataObjects"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/*"
    ]
  }

  statement {
    sid    = "ManageAthenaResults"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/athena_results/*"
    ]
  }
}

resource "aws_iam_role_policy" "mwaa_s3_access" {
  name   = "healthcare_realtime_mwaa_serverless_s3_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_s3_access.json
}

data "aws_iam_policy_document" "mwaa_glue_access" {
  statement {
    sid    = "RunHealthcareGlueJob"
    effect = "Allow"

    actions = [
      "glue:GetJob",
      "glue:StartJobRun",
      "glue:GetJobRun",
      "glue:GetJobRuns",
    ]

    resources = [
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:job/${var.glue_job_name}"
    ]
  }

  statement {
    sid    = "ReadHealthcareGlueCatalog"
    effect = "Allow"

    actions = [
      "glue:GetDatabase",
      "glue:GetTable"
    ]

    resources = [
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${var.glue_database_name}",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.glue_database_name}/*"
    ]
  }
}

resource "aws_iam_role_policy" "mwaa_glue_access" {
  name   = "healthcare_realtime_mwaa_serverless_glue_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_glue_access.json
}

data "aws_iam_policy_document" "mwaa_athena_access" {
  statement {
    sid    = "RunHealthcareAthenaQueries"
    effect = "Allow"

    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults"
    ]

    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "mwaa_athena_access" {
  name   = "healthcare_realtime_mwaa_serverless_athena_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_athena_access.json
}

data "aws_iam_policy_document" "mwaa_ecs_access" {
  statement {
    sid    = "RunHealthcareDataTasks"
    effect = "Allow"

    actions = [
      "ecs:RunTask"
    ]

    resources = [
      var.dbt_ecs_task_definition_arn,
      var.soda_ecs_task_definition_arn
    ]
  }

  statement {
    sid    = "DescribeHealthcareDataTasks"
    effect = "Allow"

    actions = [
      "ecs:DescribeTasks"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "PassHealthcareDataTaskRoles"
    effect = "Allow"

    actions = [
      "iam:PassRole"
    ]

    resources = [
      var.dbt_ecs_task_role_arn,
      var.dbt_ecs_task_execution_role_arn,
      var.soda_ecs_task_role_arn,
      var.soda_ecs_task_execution_role_arn
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"

      values = [
        "ecs-tasks.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role_policy" "mwaa_ecs_access" {
  name   = "healthcare_realtime_mwaa_serverless_ecs_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_ecs_access.json
}

resource "aws_iam_role_policy" "mwaa_logs_access" {
  name = "healthcare_realtime_mwaa_serverless_logs_access"
  role = aws_iam_role.mwaa_execution.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "WriteMwaaServerlessTaskLogs"
        Effect = "Allow"

        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]

        Resource = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/mwaa-serverless/*"
      },
    ]
  })
}

resource "awscc_mwaaserverless_workflow" "healthcare_realtime" {
  name         = var.workflow_name
  role_arn     = aws_iam_role.mwaa_execution.arn
  trigger_mode = "manual_only"

  definition_s3_location = {
    bucket     = aws_s3_bucket.mwaa.bucket
    object_key = aws_s3_object.workflow_definition.key
    version_id = aws_s3_object.workflow_definition.version_id
  }

  network_configuration = {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  encryption_configuration = {
    type = "AWS_MANAGED_KEY"
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy.mwaa_s3_access,
    aws_iam_role_policy.mwaa_glue_access,
    aws_iam_role_policy.mwaa_athena_access,
    aws_iam_role_policy.mwaa_ecs_access,
  ]
}