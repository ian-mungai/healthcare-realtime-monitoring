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

data "aws_iam_policy_document" "mwaa_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type = "Service"

      identifiers = [
        "airflow.amazonaws.com",
        "airflow-env.amazonaws.com"
      ]
    }

    actions = ["sts:AssumeRole"]
  }
}

data "aws_iam_policy_document" "mwaa_ecs_access" {
  statement {
    sid    = "RunDbtEcsTask"
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
    sid    = "DescribeDbtEcsTasks"
    effect = "Allow"

    actions = [
      "ecs:DescribeTasks"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "PassDbtEcsRoles"
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
  name   = "healthcare_realtime_mwaa_ecs_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_ecs_access.json
}

resource "aws_iam_role" "mwaa_execution" {
  name               = "healthcare_realtime_mwaa_execution_role"
  assume_role_policy = data.aws_iam_policy_document.mwaa_assume_role.json

  tags = var.tags
}

resource "aws_s3_object" "soda_lineage_helper" {
  bucket = aws_s3_bucket.mwaa.id
  key    = "dags/lib/soda_lineage.py"
  source = "${path.root}/../airflow/dags/lib/soda_lineage.py"
  etag   = filemd5("${path.root}/../airflow/dags/lib/soda_lineage.py")
}

data "aws_iam_policy_document" "mwaa_s3_access" {
  statement {
    sid    = "ReadAccountPublicAccessBlock"
    effect = "Allow"

    actions = [
      "s3:GetAccountPublicAccessBlock"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "ReadProcessedIcebergData"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/processed/*"
    ]
  }

  statement {
    sid    = "ManageOpenLineageEvents"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/lineage/openlineage/*"
    ]
  }

  statement {
    sid    = "ReadMWAASourceBucketConfiguration"
    effect = "Allow"

    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
      "s3:GetBucketPublicAccessBlock"
    ]

    resources = [
      aws_s3_bucket.mwaa.arn
    ]
  }

  statement {
    sid    = "ReadMWAASourceObjects"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]

    resources = [
      "${aws_s3_bucket.mwaa.arn}/*"
    ]
  }

  statement {
    sid    = "ReadHealthcareDataBucketConfiguration"
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
    sid    = "ReadHealthcareMetrics"
    effect = "Allow"

    actions = [
      "s3:GetObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/metrics/*"
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
  name   = "healthcare_realtime_mwaa_s3_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_s3_access.json
}

data "aws_iam_policy_document" "mwaa_glue_access" {
  statement {
    sid    = "RunHealthcareGlueJob"
    effect = "Allow"

    actions = [
      "glue:StartJobRun",
      "glue:GetJobRun",
      "glue:GetJobRuns"
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
  name   = "healthcare_realtime_mwaa_glue_access"
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
  name   = "healthcare_realtime_mwaa_athena_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_athena_access.json
}

data "aws_iam_policy_document" "mwaa_cloudwatch_access" {
  statement {
    sid    = "PublishAirflowMetrics"
    effect = "Allow"

    actions = [
      "airflow:PublishMetrics"
    ]

    resources = [
      "arn:aws:airflow:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:environment/${var.environment_name}"
    ]
  }

  statement {
    sid    = "ManageAirflowLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:CreateLogGroup",
      "logs:PutLogEvents",
      "logs:GetLogEvents",
      "logs:GetLogRecord",
      "logs:GetLogGroupFields",
      "logs:GetQueryResults"
    ]

    resources = [
      "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:airflow-${var.environment_name}-*"
    ]
  }

  statement {
    sid    = "DescribeAirflowLogGroups"
    effect = "Allow"

    actions = [
      "logs:DescribeLogGroups"
    ]

    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "mwaa_cloudwatch_access" {
  name   = "healthcare_realtime_mwaa_cloudwatch_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_cloudwatch_access.json
}

data "aws_iam_policy_document" "mwaa_sqs_access" {
  statement {
    sid    = "ManageAirflowCeleryQueues"
    effect = "Allow"

    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ReceiveMessage",
      "sqs:SendMessage"
    ]

    resources = [
      "arn:aws:sqs:${data.aws_region.current.region}:*:airflow-celery-*"
    ]
  }
}

resource "aws_iam_role_policy" "mwaa_sqs_access" {
  name   = "healthcare_realtime_mwaa_sqs_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_sqs_access.json
}

data "aws_iam_policy_document" "mwaa_kms_access" {
  statement {
    sid    = "UseAWSOwnedEncryptionKeys"
    effect = "Allow"

    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:GenerateDataKey*",
      "kms:Encrypt"
    ]

    not_resources = [
      "arn:aws:kms:*:${data.aws_caller_identity.current.account_id}:key/*"
    ]

    condition {
      test     = "StringLike"
      variable = "kms:ViaService"

      values = [
        "sqs.${data.aws_region.current.region}.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role_policy" "mwaa_kms_access" {
  name   = "healthcare_realtime_mwaa_kms_access"
  role   = aws_iam_role.mwaa_execution.id
  policy = data.aws_iam_policy_document.mwaa_kms_access.json
}

resource "aws_s3_object" "dag" {
  bucket = aws_s3_bucket.mwaa.id
  key    = "dags/healthcare_realtime_pipeline.py"
  source = "${path.root}/../airflow/dags/healthcare_realtime_pipeline.py"
  etag   = filemd5("${path.root}/../airflow/dags/healthcare_realtime_pipeline.py")
}

resource "aws_s3_object" "openlineage_helper" {
  bucket = aws_s3_bucket.mwaa.id
  key    = "dags/lib/openlineage_events.py"
  source = "${path.root}/../airflow/dags/lib/openlineage_events.py"
  etag   = filemd5("${path.root}/../airflow/dags/lib/openlineage_events.py")
}

resource "aws_s3_object" "athena_lineage_helper" {
  bucket = aws_s3_bucket.mwaa.id
  key    = "dags/lib/athena_lineage.py"
  source = "${path.root}/../airflow/dags/lib/athena_lineage.py"
  etag   = filemd5("${path.root}/../airflow/dags/lib/athena_lineage.py")
}

resource "aws_s3_object" "dag_lib_init" {
  bucket = aws_s3_bucket.mwaa.id
  key    = "dags/lib/__init__.py"
  source = "${path.root}/../airflow/dags/lib/__init__.py"
  etag   = filemd5("${path.root}/../airflow/dags/lib/__init__.py")
}

resource "aws_s3_object" "requirements" {
  bucket = aws_s3_bucket.mwaa.id
  key    = "requirements.txt"
  source = "${path.root}/../airflow/requirements.txt"
  etag   = filemd5("${path.root}/../airflow/requirements.txt")
}

resource "aws_s3_object" "dbt_lineage_helper" {
  bucket = aws_s3_bucket.mwaa.id
  key    = "dags/lib/dbt_lineage.py"
  source = "${path.root}/../airflow/dags/lib/dbt_lineage.py"
  etag   = filemd5("${path.root}/../airflow/dags/lib/dbt_lineage.py")
}

resource "aws_mwaa_environment" "healthcare_realtime" {
  name = var.environment_name

  execution_role_arn = aws_iam_role.mwaa_execution.arn
  source_bucket_arn  = aws_s3_bucket.mwaa.arn

  dag_s3_path = "dags"

  requirements_s3_path           = aws_s3_object.requirements.key
  requirements_s3_object_version = aws_s3_object.requirements.version_id

  network_configuration {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  webserver_access_mode = "PUBLIC_ONLY"

  environment_class = "mw1.micro"

  min_workers = 1
  max_workers = 1
  schedulers  = 1

  logging_configuration {
    dag_processing_logs {
      enabled   = true
      log_level = "INFO"
    }

    scheduler_logs {
      enabled   = true
      log_level = "INFO"
    }

    task_logs {
      enabled   = true
      log_level = "INFO"
    }

    webserver_logs {
      enabled   = true
      log_level = "INFO"
    }

    worker_logs {
      enabled   = true
      log_level = "INFO"
    }
  }

  airflow_configuration_options = merge(
    {
      "core.load_examples" = "False"
    },
    {
      "dbt.ecs_security_group"  = var.dbt_ecs_security_group_id
      "dbt.ecs_subnets"         = join(",", var.dbt_ecs_subnet_ids)
      "soda.ecs_security_group" = var.soda_ecs_security_group_id
      "soda.ecs_subnets"        = join(",", var.soda_ecs_subnet_ids)
    }
  )

  tags = var.tags

  depends_on = [
    aws_s3_bucket_versioning.mwaa,
    aws_s3_bucket_public_access_block.mwaa,
    aws_s3_object.dag,
    aws_s3_object.openlineage_helper,
    aws_s3_object.athena_lineage_helper,
    aws_s3_object.dbt_lineage_helper,
    aws_s3_object.soda_lineage_helper,
    aws_s3_object.dag_lib_init,
    aws_s3_object.requirements,
    aws_iam_role_policy.mwaa_s3_access,
    aws_iam_role_policy.mwaa_glue_access,
    aws_iam_role_policy.mwaa_athena_access,
    aws_iam_role_policy.mwaa_cloudwatch_access,
    aws_iam_role_policy.mwaa_sqs_access,
    aws_iam_role_policy.mwaa_kms_access,
    aws_iam_role_policy.mwaa_ecs_access,
  ]
}