resource "aws_ecr_repository" "vitals_simulator" {
  name                 = "healthcare-realtime-vitals-simulator"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "vitals_simulator" {
  repository = aws_ecr_repository.vitals_simulator.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the 20 most recent simulator images"
        selection = {
          tagStatus = "tagged"
          tagPrefixList = [
            "sha-"
          ]
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
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

resource "aws_cloudwatch_log_group" "vitals_simulator" {
  name              = "/ecs/healthcare-realtime-vitals-simulator"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_iam_role" "task_execution" {
  name               = "healthcare_realtime_vitals_simulator_execution_role"
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
    sid    = "PullVitalsSimulatorImage"
    effect = "Allow"

    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage"
    ]

    resources = [
      aws_ecr_repository.vitals_simulator.arn
    ]
  }

  statement {
    sid    = "WriteVitalsSimulatorLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]

    resources = [
      "${aws_cloudwatch_log_group.vitals_simulator.arn}:*"
    ]
  }
}

resource "aws_iam_role_policy" "task_execution" {
  name   = "healthcare_realtime_vitals_simulator_execution"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution.json
}

resource "aws_iam_role" "task" {
  name               = "healthcare_realtime_vitals_simulator_task_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid    = "ReadFHIRResourceMap"
    effect = "Allow"

    actions = [
      "s3:GetObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/${var.resource_map_s3_key}"
    ]
  }

  statement {
    sid    = "ReadWriteBIDMCCache"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]

    resources = [
      "arn:aws:s3:::${var.data_bucket_name}/cache/vitals_simulator/bidmc/*"
    ]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "healthcare_realtime_vitals_simulator_task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_security_group" "vitals_simulator" {
  name        = "healthcare-realtime-vitals-simulator"
  description = "Outbound access for the realtime vitals simulator."
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_ecs_task_definition" "vitals_simulator" {
  family                   = "healthcare_realtime_vitals_simulator"
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
      name      = "vitals_simulator"
      image     = "${aws_ecr_repository.vitals_simulator.repository_url}:${var.image_tag}"
      essential = true

      environment = [
        {
          name  = "FHIR_BASE_URL"
          value = var.fhir_base_url
        },
        {
          name  = "FHIR_RESOURCE_MAP_S3_BUCKET"
          value = var.data_bucket_name
        },
        {
          name  = "FHIR_RESOURCE_MAP_S3_KEY"
          value = var.resource_map_s3_key
        },
        {
          name  = "BIDMC_CACHE_S3_BUCKET"
          value = var.data_bucket_name
        },
        {
          name  = "BIDMC_CACHE_S3_PREFIX"
          value = "cache/vitals_simulator/bidmc"
        },
        {
          name  = "BIDMC_FETCH_MAX_ATTEMPTS"
          value = "5"
        },
        {
          name  = "BIDMC_FETCH_BACKOFF_SECONDS"
          value = "2"
        },
        {
          name  = "SIMULATOR_INTERVAL_SECONDS"
          value = "5"
        },
        {
          name  = "SIMULATOR_BP_INTERVAL_SECONDS"
          value = "300"
        },
        {
          name  = "SIMULATOR_MAX_CYCLES"
          value = "unlimited"
        },
        {
          name  = "SIMULATOR_REPLAY"
          value = "true"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.vitals_simulator.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "vitals-simulator"
        }
      }
    }
  ])

  tags = var.tags
}
