data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  port         = 3000
  results_path = "athena_results/grafana/"
  region       = data.aws_region.current.region
  account_id   = data.aws_caller_identity.current.account_id
}

resource "aws_ecr_repository" "grafana" {
  name                 = "healthcare-realtime-grafana"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.allow_destructive_teardown

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "grafana" {
  repository = aws_ecr_repository.grafana.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the ten newest Grafana images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "grafana" {
  count = var.enabled ? 1 : 0

  name              = "/ecs/healthcare-realtime-grafana"
  retention_in_days = 14

  tags = var.tags
}

# The operator creates the admin password secret before the apply (docs/external-prerequisites.md), so its value never
# enters Terraform. The task reads it at start; teardown leaves it in place.
data "aws_secretsmanager_secret" "admin" {
  count = var.enabled ? 1 : 0

  name = "healthcare-realtime/grafana-admin"
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "task_execution" {
  count = var.enabled ? 1 : 0

  name               = "healthcare_realtime_grafana_execution_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task_execution" {
  count = var.enabled ? 1 : 0

  statement {
    sid       = "GetEcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullGrafanaImage"
    effect = "Allow"

    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]

    resources = [aws_ecr_repository.grafana.arn]
  }

  statement {
    sid       = "WriteContainerLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.grafana[0].arn}:*"]
  }

  statement {
    sid       = "ReadGrafanaAdminPassword"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [data.aws_secretsmanager_secret.admin[0].arn]
  }
}

resource "aws_iam_role_policy" "task_execution" {
  count = var.enabled ? 1 : 0

  name   = "healthcare_realtime_grafana_execution"
  role   = aws_iam_role.task_execution[0].id
  policy = data.aws_iam_policy_document.task_execution[0].json
}

resource "aws_iam_role" "task" {
  count = var.enabled ? 1 : 0

  name               = "healthcare_realtime_grafana_task_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

# Read-only access to the warehouse through Athena, plus the ECS Exec channel the operator's port forward uses.
data "aws_iam_policy_document" "task" {
  count = var.enabled ? 1 : 0

  statement {
    sid    = "RunAthenaQueries"
    effect = "Allow"

    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup"
    ]

    resources = ["arn:aws:athena:${local.region}:${local.account_id}:workgroup/${var.athena_workgroup_name}"]
  }

  statement {
    sid    = "ReadAthenaCatalog"
    effect = "Allow"

    actions = [
      "athena:GetDataCatalog",
      "athena:GetDatabase",
      "athena:GetTableMetadata",
      "athena:ListDatabases",
      "athena:ListTableMetadata",
      "athena:ListDataCatalogs",
      "athena:ListWorkGroups"
    ]

    # Athena names the default Glue catalog AwsDataCatalog; clients may pass it in lower case.
    resources = concat(
      [for name in distinct([var.athena_catalog_name, "AwsDataCatalog"]) : "arn:aws:athena:${local.region}:${local.account_id}:datacatalog/${name}"],
      ["arn:aws:athena:${local.region}:${local.account_id}:workgroup/${var.athena_workgroup_name}"]
    )
  }

  statement {
    sid    = "ReadGlueCatalog"
    effect = "Allow"

    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition"
    ]

    resources = [
      "arn:aws:glue:${local.region}:${local.account_id}:catalog",
      "arn:aws:glue:${local.region}:${local.account_id}:database/${var.source_database_name}",
      "arn:aws:glue:${local.region}:${local.account_id}:database/${var.dbt_database_name}",
      "arn:aws:glue:${local.region}:${local.account_id}:table/${var.source_database_name}/*",
      "arn:aws:glue:${local.region}:${local.account_id}:table/${var.dbt_database_name}/*"
    ]
  }

  statement {
    sid       = "ListHealthcareBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = ["arn:aws:s3:::${var.data_bucket_name}"]
  }

  statement {
    sid     = "ReadHealthcareData"
    effect  = "Allow"
    actions = ["s3:GetObject"]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/processed/*",
      "arn:aws:s3:::${var.data_bucket_name}/quarantine/*",
      "arn:aws:s3:::${var.data_bucket_name}/dbt/*"
    ]
  }

  statement {
    sid    = "ManageGrafanaAthenaResults"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts"
    ]

    resources = ["arn:aws:s3:::${var.data_bucket_name}/${local.results_path}*"]
  }

  statement {
    sid    = "OpenExecChannel"
    effect = "Allow"

    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel"
    ]

    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task" {
  count = var.enabled ? 1 : 0

  name   = "healthcare_realtime_grafana_task"
  role   = aws_iam_role.task[0].id
  policy = data.aws_iam_policy_document.task[0].json
}

# No inbound rule: operators reach Grafana only through an SSM port forward, which the task opens outbound.
resource "aws_security_group" "grafana" {
  count = var.enabled ? 1 : 0

  name        = "healthcare-realtime-grafana"
  description = "Grafana ECS task: no inbound access; outbound HTTPS to AWS APIs through the NAT gateway."
  vpc_id      = var.vpc_id

  egress {
    description = "Outbound HTTPS to Athena, Secrets Manager, SSM and ECR through the NAT gateway"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_ecs_task_definition" "grafana" {
  count = var.enabled ? 1 : 0

  family                   = "healthcare_realtime_grafana"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  cpu    = "512"
  memory = "1024"

  execution_role_arn = aws_iam_role.task_execution[0].arn
  task_role_arn      = aws_iam_role.task[0].arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "grafana"
      image     = "${aws_ecr_repository.grafana.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = local.port
          protocol      = "tcp"
        }
      ]

      # Read by the provisioned Athena data source (deploy/grafana/provisioning/datasources/athena.yaml).
      environment = [
        { name = "ATHENA_REGION", value = local.region },
        { name = "ATHENA_CATALOG", value = var.athena_catalog_name },
        { name = "ATHENA_DATABASE", value = var.dbt_database_name },
        { name = "ATHENA_WORKGROUP", value = var.athena_workgroup_name },
        { name = "ATHENA_RESULTS_S3_URI", value = "s3://${var.data_bucket_name}/${local.results_path}" }
      ]

      secrets = [
        {
          name      = "GF_SECURITY_ADMIN_PASSWORD"
          valueFrom = data.aws_secretsmanager_secret.admin[0].arn
        }
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "wget -q --spider http://127.0.0.1:${local.port}/api/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      # ECS Exec needs an init process to reap the SSM agent's child processes.
      linuxParameters = {
        initProcessEnabled = true
      }

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.grafana[0].name
          awslogs-region        = local.region
          awslogs-stream-prefix = "grafana"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "grafana" {
  count = var.enabled ? 1 : 0

  name            = "healthcare_realtime_grafana"
  cluster         = var.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.grafana[0].arn

  desired_count    = var.desired_count
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  # The operator's SSM port forward runs through ECS Exec.
  enable_execute_command = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.grafana[0].id]
    assign_public_ip = false
  }

  tags = var.tags
}
