data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_ecr_repository" "dbt" {
  name                 = "healthcare-realtime-dbt"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.force_delete_repository

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_ecs_cluster" "dbt" {
  name = "healthcare-realtime-data-jobs"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "dbt" {
  name              = "/ecs/healthcare-realtime-dbt"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_cloudwatch_log_metric_filter" "openlineage_emission_failures" {
  name           = "healthcare-realtime-dbt-openlineage-emission-failures"
  pattern        = "\"OpenLineage\" \"emission\" \"failed\""
  log_group_name = aws_cloudwatch_log_group.dbt.name

  metric_transformation {
    name      = "EmissionFailure"
    namespace = "HealthcareRealtime/OpenLineage"
    value     = "1"
  }
}

resource "aws_glue_catalog_database" "ml" {
  name = var.ml_database_name
}

resource "aws_glue_catalog_table" "predictions" {
  name          = "ml_predictions_published"
  database_name = aws_glue_catalog_database.ml.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
    EXTERNAL       = "TRUE"
  }

  partition_keys {
    name = "model_version"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.data_bucket_name}/ml/predictions/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    dynamic "columns" {
      for_each = {
        encounter_key             = "string"
        patient_key               = "string"
        data_split                = "string"
        actual_label              = "int"
        deterioration_probability = "double"
        predicted_label           = "int"
        decision_threshold        = "double"
        feature_schema_version    = "string"
        label_definition_version  = "string"
        dataset_fingerprint       = "string"
        scored_at                 = "timestamp"
      }

      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type = "Service"

      identifiers = [
        "ecs-tasks.amazonaws.com"
      ]
    }

    actions = [
      "sts:AssumeRole"
    ]
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "healthcare_realtime_dbt_execution_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task_execution" {
  statement {
    sid    = "GetECRAuthorization"
    effect = "Allow"

    actions = [
      "ecr:GetAuthorizationToken"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "PullDbtImage"
    effect = "Allow"

    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]

    resources = [
      aws_ecr_repository.dbt.arn
    ]
  }

  statement {
    sid    = "WriteDbtContainerLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]

    resources = [
      "${aws_cloudwatch_log_group.dbt.arn}:*"
    ]
  }
}

resource "aws_iam_role_policy" "task_execution" {
  name   = "healthcare_realtime_dbt_execution"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution.json
}

resource "aws_iam_role" "task" {
  name               = "healthcare_realtime_dbt_task_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid    = "RunAthenaQueries"
    effect = "Allow"

    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
      "athena:GetDataCatalog",
      "athena:GetDatabase",
      "athena:GetTableMetadata",
      "athena:ListDatabases",
      "athena:ListTableMetadata"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "ReadGlueCatalog"
    effect = "Allow"

    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetTableVersion",
      "glue:GetTableVersions",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition"
    ]

    resources = [
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${var.source_database_name}",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.source_database_name}/*",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${var.dbt_database_name}",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.dbt_database_name}/*",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${var.ml_database_name}",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.ml_database_name}/*"
    ]
  }

  statement {
    sid    = "RegisterModelPredictionPartitions"
    effect = "Allow"

    actions = [
      "glue:CreatePartition",
      "glue:BatchCreatePartition"
    ]

    resources = [
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${var.ml_database_name}",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.ml_database_name}/ml_predictions_published"
    ]
  }

  statement {
    sid    = "ManageDbtGlueCatalog"
    effect = "Allow"

    actions = [
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:BatchDeleteTable",
      "glue:DeleteTableVersion",
      "glue:BatchDeleteTableVersion",
      "glue:CreatePartition",
      "glue:BatchCreatePartition",
      "glue:UpdatePartition",
      "glue:DeletePartition",
      "glue:BatchDeletePartition"
    ]

    resources = [
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${var.dbt_database_name}",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.dbt_database_name}/*"
    ]
  }

  statement {
    sid    = "ListHealthcareDataBucket"
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
    sid    = "ReadProcessedHealthcareData"
    effect = "Allow"

    actions = [
      "s3:GetObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/processed/*",
      "arn:aws:s3:::${var.data_bucket_name}/ml/predictions/*",
      "arn:aws:s3:::${var.data_bucket_name}/ml/model_artifacts/${var.approved_model_version}/*"
    ]
  }

  statement {
    sid    = "PublishApprovedModelPredictions"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/ml/predictions/model_version=${var.approved_model_version}/*"
    ]
  }

  statement {
    sid    = "ManageDbtAthenaResults"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/athena_results/dbt/*",
      "arn:aws:s3:::${var.data_bucket_name}/athena_results/ml_scoring/*"
    ]
  }

  statement {
    sid    = "ManageDbtData"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/dbt/*"
    ]
  }

  statement {
    sid    = "WriteDbtOpenLineageEvents"
    effect = "Allow"

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/lineage/openlineage/dbt/*"
    ]
  }

  dynamic "statement" {
    for_each = var.openlineage_collector_invoke_arn == "" ? [] : [var.openlineage_collector_invoke_arn]

    content {
      sid       = "PublishOpenLineageEvents"
      effect    = "Allow"
      actions   = ["execute-api:Invoke"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "healthcare_realtime_dbt_task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_security_group" "dbt" {
  name        = "healthcare-realtime-dbt"
  description = "Outbound access for dbt ECS Fargate tasks."
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_ecs_task_definition" "dbt" {
  family                   = "healthcare_realtime_dbt"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  cpu    = "256"
  memory = "512"

  execution_role_arn = aws_iam_role.task_execution.arn
  task_role_arn      = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "dbt"
      image     = "${aws_ecr_repository.dbt.repository_url}:${var.image_tag}"
      essential = true

      command = [
        "build",
        "--project-dir",
        "/app/dbt",
        "--profiles-dir",
        "/app"
      ]

      environment = [
        {
          name  = "AWS_REGION"
          value = data.aws_region.current.region
        },
        {
          name  = "DATA_BUCKET_NAME"
          value = var.data_bucket_name
        },
        {
          name  = "OPENLINEAGE_URL"
          value = var.openlineage_collector_url
        },
        {
          name  = "ML_APPROVED_MODEL_VERSION"
          value = var.approved_model_version
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.dbt.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "dbt"
        }
      }
    }
  ])

  tags = var.tags
}
