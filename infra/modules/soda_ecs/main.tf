data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_ecr_repository" "soda" {
  name                 = "healthcare-realtime-soda"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "soda" {
  name              = "/ecs/healthcare-realtime-soda"
  retention_in_days = 14

  tags = var.tags
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
  name               = "healthcare_realtime_soda_execution_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task_execution" {
  statement {
    sid    = "GetEcrAuthorization"
    effect = "Allow"

    actions = [
      "ecr:GetAuthorizationToken"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "PullSodaImage"
    effect = "Allow"

    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]

    resources = [
      aws_ecr_repository.soda.arn
    ]
  }

  statement {
    sid    = "WriteContainerLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]

    resources = [
      "${aws_cloudwatch_log_group.soda.arn}:*"
    ]
  }
}

resource "aws_iam_role_policy" "task_execution" {
  name   = "healthcare_realtime_soda_execution"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution.json
}

resource "aws_iam_role" "task" {
  name               = "healthcare_realtime_soda_task_role"
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
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${var.dbt_database_name}",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.source_database_name}/*",
      "arn:aws:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${var.dbt_database_name}/*"
    ]
  }

  statement {
    sid    = "ListHealthcareBucket"
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
    sid    = "WriteSodaOpenLineageEvents"
    effect = "Allow"

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/lineage/openlineage/soda/*"
    ]
  }
  statement {
    sid    = "ReadHealthcareData"
    effect = "Allow"

    actions = [
      "s3:GetObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/processed/*",
      "arn:aws:s3:::${var.data_bucket_name}/dbt/*"
    ]
  }

  statement {
    sid    = "ManageSodaAthenaResults"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/athena_results/soda/*"
    ]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "healthcare_realtime_soda_task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_security_group" "soda" {
  name        = "healthcare-realtime-soda"
  description = "Outbound access for Soda ECS Fargate tasks."
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_ecs_task_definition" "soda" {
  family                   = "healthcare_realtime_soda"
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
      name      = "soda"
      image     = "${aws_ecr_repository.soda.repository_url}:${var.image_tag}"
      essential = true

      environment = [
        {
          name  = "AWS_REGION"
          value = data.aws_region.current.region
        },
        {
          name  = "DATA_BUCKET_NAME"
          value = var.data_bucket_name
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.soda.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "soda"
        }
      }
    }
  ])

  tags = var.tags
}
