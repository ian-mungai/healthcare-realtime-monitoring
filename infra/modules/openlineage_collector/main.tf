data "aws_region" "current" {}

resource "aws_ecr_repository" "marquez" {
  name                 = "healthcare-realtime-marquez"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "marquez" {
  repository = aws_ecr_repository.marquez.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the ten newest Marquez images"
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

resource "aws_cloudwatch_log_group" "marquez" {
  count = var.enabled ? 1 : 0

  name              = "/ecs/healthcare-realtime-marquez"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "api" {
  count = var.enabled ? 1 : 0

  name              = "/aws/apigateway/healthcare-realtime-openlineage"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_security_group" "vpc_link" {
  count = var.enabled ? 1 : 0

  name        = "healthcare-realtime-openlineage-vpc-link"
  description = "Outbound access from API Gateway to the private Marquez load balancer."
  vpc_id      = var.vpc_id

  egress {
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_security_group" "load_balancer" {
  count = var.enabled ? 1 : 0

  name        = "healthcare-realtime-openlineage-alb"
  description = "Private Marquez load balancer access from API Gateway only."
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.vpc_link[0].id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_security_group" "marquez" {
  count = var.enabled ? 1 : 0

  name        = "healthcare-realtime-marquez"
  description = "Marquez API access from its private load balancer."
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.load_balancer[0].id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_security_group" "database" {
  count = var.enabled ? 1 : 0

  name        = "healthcare-realtime-marquez-database"
  description = "PostgreSQL access from Marquez only."
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.marquez[0].id]
  }

  tags = var.tags
}

resource "aws_db_subnet_group" "marquez" {
  count = var.enabled ? 1 : 0

  name       = "healthcare-realtime-marquez"
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, { Name = "healthcare-realtime-marquez" })
}

resource "aws_db_instance" "marquez" {
  count = var.enabled ? 1 : 0

  identifier = "healthcare-realtime-marquez"

  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "marquez"
  username = "marquez_admin"

  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.marquez[0].name
  vpc_security_group_ids = [aws_security_group.database[0].id]

  publicly_accessible = false
  multi_az            = false

  backup_retention_period    = 7
  auto_minor_version_upgrade = true
  apply_immediately          = true

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "healthcare-realtime-marquez-final"

  tags = var.tags
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  count = var.enabled ? 1 : 0

  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "execution" {
  count = var.enabled ? 1 : 0

  name               = "healthcare_realtime_marquez_execution_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role[0].json

  tags = var.tags
}

data "aws_iam_policy_document" "execution" {
  count = var.enabled ? 1 : 0

  statement {
    sid       = "GetEcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullMarquezImage"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = [aws_ecr_repository.marquez.arn]
  }

  statement {
    sid    = "WriteMarquezLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.marquez[0].arn}:*"]
  }

  statement {
    sid       = "ReadMarquezDatabaseCredentials"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.marquez[0].master_user_secret[0].secret_arn]
  }
}

resource "aws_iam_role_policy" "execution" {
  count = var.enabled ? 1 : 0

  name   = "healthcare_realtime_marquez_execution"
  role   = aws_iam_role.execution[0].id
  policy = data.aws_iam_policy_document.execution[0].json
}

resource "aws_ecs_task_definition" "marquez" {
  count = var.enabled ? 1 : 0

  family                   = "healthcare_realtime_marquez"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution[0].arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "marquez"
      image     = "${aws_ecr_repository.marquez.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 5000
          hostPort      = 5000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "MARQUEZ_PORT", value = "5000" },
        { name = "MARQUEZ_ADMIN_PORT", value = "5001" },
        { name = "POSTGRES_HOST", value = aws_db_instance.marquez[0].address },
        { name = "POSTGRES_PORT", value = tostring(aws_db_instance.marquez[0].port) },
        { name = "POSTGRES_DB", value = aws_db_instance.marquez[0].db_name },
        { name = "JAVA_OPTS", value = "-Xms256m -Xmx640m" },
      ]

      secrets = [
        {
          name      = "POSTGRES_USER"
          valueFrom = "${aws_db_instance.marquez[0].master_user_secret[0].secret_arn}:username::"
        },
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "${aws_db_instance.marquez[0].master_user_secret[0].secret_arn}:password::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.marquez[0].name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "marquez"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_lb" "marquez" {
  count = var.enabled ? 1 : 0

  name               = "healthcare-realtime-lineage"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.load_balancer[0].id]
  subnets            = var.private_subnet_ids

  tags = var.tags
}

resource "aws_lb_target_group" "marquez" {
  count = var.enabled ? 1 : 0

  name        = "healthcare-realtime-lineage"
  port        = 5000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    path                = "/api/v1/namespaces"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  tags = var.tags
}

resource "aws_lb_listener" "marquez" {
  count = var.enabled ? 1 : 0

  load_balancer_arn = aws_lb.marquez[0].arn
  port              = 5000
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.marquez[0].arn
  }

  tags = var.tags
}

resource "aws_ecs_service" "marquez" {
  count = var.enabled ? 1 : 0

  name            = "healthcare_realtime_marquez"
  cluster         = var.ecs_cluster_arn
  task_definition = aws_ecs_task_definition.marquez[0].arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  platform_version                  = "LATEST"
  health_check_grace_period_seconds = 300
  wait_for_steady_state             = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.marquez[0].id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.marquez[0].arn
    container_name   = "marquez"
    container_port   = 5000
  }

  depends_on = [aws_lb_listener.marquez]

  tags = var.tags
}

resource "aws_apigatewayv2_vpc_link" "marquez" {
  count = var.enabled ? 1 : 0

  name               = "healthcare-realtime-openlineage"
  security_group_ids = [aws_security_group.vpc_link[0].id]
  subnet_ids         = var.private_subnet_ids

  tags = var.tags
}

resource "aws_apigatewayv2_api" "marquez" {
  count = var.enabled ? 1 : 0

  name          = "healthcare-realtime-openlineage"
  protocol_type = "HTTP"

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "marquez" {
  count = var.enabled ? 1 : 0

  api_id                 = aws_apigatewayv2_api.marquez[0].id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = aws_lb_listener.marquez[0].arn
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.marquez[0].id
  payload_format_version = "1.0"

  request_parameters = {
    "overwrite:path" = "$request.path"
  }
}

resource "aws_apigatewayv2_route" "lineage" {
  count = var.enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.marquez[0].id
  route_key          = "POST /api/v1/lineage"
  target             = "integrations/${aws_apigatewayv2_integration.marquez[0].id}"
  authorization_type = "AWS_IAM"
}

resource "aws_apigatewayv2_route" "read_root" {
  count = var.enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.marquez[0].id
  route_key          = "GET /"
  target             = "integrations/${aws_apigatewayv2_integration.marquez[0].id}"
  authorization_type = "AWS_IAM"
}

resource "aws_apigatewayv2_route" "read_proxy" {
  count = var.enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.marquez[0].id
  route_key          = "GET /{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.marquez[0].id}"
  authorization_type = "AWS_IAM"
}

resource "aws_apigatewayv2_stage" "development" {
  count = var.enabled ? 1 : 0

  api_id      = aws_apigatewayv2_api.marquez[0].id
  name        = var.stage_name
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api[0].arn
    format = jsonencode({
      requestId        = "$context.requestId"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      integrationError = "$context.integrationErrorMessage"
    })
  }

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }

  tags = var.tags
}
