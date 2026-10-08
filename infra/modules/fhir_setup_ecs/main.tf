# One-off ECS task that loads the synthetic cohort into HAPI FHIR and registers the webhook subscription from inside
# the VPC, so the HAPI load balancer only has to accept the NAT gateway (docs/fhir-setup-tasks.md). It reuses the vitals
# simulator image, which carries the loader and subscription code.

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "fhir_setup" {
  name              = "/ecs/healthcare-realtime-fhir-setup"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_iam_role" "task_execution" {
  name               = "healthcare_realtime_fhir_setup_execution_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task_execution" {
  statement {
    sid       = "GetECRAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullSimulatorImage"
    effect = "Allow"

    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]

    resources = [var.image_repository_arn]
  }

  statement {
    sid       = "WriteFHIRSetupLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fhir_setup.arn}:*"]
  }
}

resource "aws_iam_role_policy" "task_execution" {
  name   = "healthcare_realtime_fhir_setup_execution"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution.json
}

resource "aws_iam_role" "task" {
  name               = "healthcare_realtime_fhir_setup_task_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "ListSeedBundles"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.data_bucket_name}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.seed_bundles_s3_prefix}/*"]
    }
  }

  statement {
    sid       = "ReadSeedBundles"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.data_bucket_name}/${var.seed_bundles_s3_prefix}/*"]
  }

  statement {
    sid       = "PublishResourceMap"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.data_bucket_name}/${var.resource_map_s3_key}"]
  }

  # The daily reference extract reads the published map and replaces one object per reference table.
  statement {
    sid       = "ReadResourceMap"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.data_bucket_name}/${var.resource_map_s3_key}"]
  }

  statement {
    sid       = "WriteCohortReference"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.data_bucket_name}/${var.cohort_reference_s3_prefix}/*"]
  }

  statement {
    sid       = "ReadWebhookSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:${data.aws_partition.current.partition}:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.webhook_secret_id}-*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "healthcare_realtime_fhir_setup_task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_security_group" "fhir_setup" {
  name        = "healthcare-realtime-fhir-setup"
  description = "Outbound access for the one-off FHIR setup task."
  vpc_id      = var.vpc_id

  egress {
    description = "HAPI FHIR through the NAT gateway and AWS APIs"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_ecs_task_definition" "fhir_setup" {
  family                   = "healthcare_realtime_fhir_setup"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  # The reference extract reads every Synthea bundle (about 2 GiB peak for the 100-patient output, measured Oct 8
  # 2026); 4 GiB is Fargate's limit for 0.5 vCPU.
  cpu    = "512"
  memory = "4096"

  execution_role_arn = aws_iam_role.task_execution.arn
  task_role_arn      = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "fhir_setup"
      image     = "${var.image_repository_url}:${var.image_tag}"
      essential = true
      command   = ["python", "-m", "jobs.fhir_setup.task", "load"]

      environment = [
        { name = "FHIR_BASE_URL", value = var.fhir_base_url },
        { name = "FHIR_RESOURCE_MAP_S3_BUCKET", value = var.data_bucket_name },
        { name = "FHIR_RESOURCE_MAP_S3_KEY", value = var.resource_map_s3_key },
        { name = "SEED_BUNDLES_S3_PREFIX", value = var.seed_bundles_s3_prefix },
        { name = "COHORT_REFERENCE_S3_PREFIX", value = var.cohort_reference_s3_prefix },
        { name = "FHIR_WEBHOOK_SECRET_ID", value = var.webhook_secret_id },
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      ]

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.fhir_setup.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "fhir-setup"
        }
      }
    }
  ])

  tags = var.tags
}
