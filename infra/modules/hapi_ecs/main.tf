data "aws_region" "current" {}

resource "aws_ecs_cluster" "services" {
  name = "healthcare-realtime-services"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "hapi" {
  name              = "/ecs/healthcare-realtime-hapi"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_security_group" "alb" {
  name        = "healthcare-realtime-hapi-alb"
  description = "Public HTTP access to the HAPI FHIR load balancer."
  vpc_id      = var.vpc_id

  ingress {
    description = "Allow HTTP access to HAPI FHIR"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow outbound traffic from the HAPI ALB"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_security_group" "hapi" {
  name        = "healthcare-realtime-hapi"
  description = "Network access for the HAPI FHIR ECS service."
  vpc_id      = var.vpc_id

  ingress {
    description     = "Allow HAPI traffic from the Application Load Balancer"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Allow outbound HAPI traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_security_group" "database" {
  name        = "healthcare-realtime-hapi-database"
  description = "PostgreSQL access from HAPI FHIR only."
  vpc_id      = var.vpc_id

  ingress {
    description     = "Allow PostgreSQL from HAPI FHIR"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.hapi.id]
  }

  tags = var.tags
}

resource "aws_db_subnet_group" "hapi" {
  name       = "healthcare-realtime-hapi"
  subnet_ids = var.private_subnet_ids

  tags = merge(
    var.tags,
    {
      Name = "healthcare-realtime-hapi"
    }
  )
}

resource "aws_db_instance" "hapi" {
  identifier = "healthcare-realtime-hapi"

  engine         = "postgres"
  engine_version = "16"

  instance_class = "db.t4g.micro"

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "hapi"
  username = "hapi_admin"

  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.hapi.name
  vpc_security_group_ids = [aws_security_group.database.id]

  publicly_accessible = false
  multi_az            = false

  backup_retention_period    = 1
  auto_minor_version_upgrade = true
  apply_immediately          = true

  deletion_protection = true
  skip_final_snapshot = true

  tags = var.tags
}

resource "aws_lb" "hapi" {
  name               = "healthcare-realtime-hapi"
  internal           = false
  load_balancer_type = "application"

  security_groups = [
    aws_security_group.alb.id
  ]

  subnets = var.public_subnet_ids

  tags = var.tags
}

resource "aws_lb_target_group" "hapi" {
  name        = "healthcare-realtime-hapi"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    path                = "/fhir/metadata"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  tags = var.tags
}

resource "aws_lb_listener" "hapi" {
  load_balancer_arn = aws_lb.hapi.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.hapi.arn
  }

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
  name               = "healthcare_realtime_hapi_execution_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

data "aws_iam_policy_document" "task_execution" {
  statement {
    sid    = "WriteHapiContainerLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]

    resources = [
      "${aws_cloudwatch_log_group.hapi.arn}:*"
    ]
  }

  statement {
    sid    = "ReadHapiDatabaseCredentials"
    effect = "Allow"

    actions = [
      "secretsmanager:GetSecretValue"
    ]

    resources = [
      aws_db_instance.hapi.master_user_secret[0].secret_arn
    ]
  }
}

resource "aws_iam_role_policy" "task_execution" {
  name   = "healthcare_realtime_hapi_execution"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution.json
}

resource "aws_iam_role" "task" {
  name               = "healthcare_realtime_hapi_task_role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = var.tags
}

resource "aws_ecs_task_definition" "hapi" {
  family                   = "healthcare_realtime_hapi"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  cpu    = "1024"
  memory = "2048"

  execution_role_arn = aws_iam_role.task_execution.arn
  task_role_arn      = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "hapi"
      image     = "hapiproject/hapi:v8.10.0-3"
      essential = true

      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "SPRING_DATASOURCE_URL"
          value = "jdbc:postgresql://${aws_db_instance.hapi.address}:${aws_db_instance.hapi.port}/${aws_db_instance.hapi.db_name}"
        },
        {
          name  = "SPRING_DATASOURCE_DRIVER_CLASS_NAME"
          value = "org.postgresql.Driver"
        },
        {
          name  = "HIBERNATE_DIALECT"
          value = "ca.uhn.fhir.jpa.model.dialect.HapiFhirPostgresDialect"
        },
        {
          name  = "SPRING_JPA_PROPERTIES_HIBERNATE_SEARCH_ENABLED"
          value = "false"
        },
        {
          name  = "HAPI_FHIR_FHIR_VERSION"
          value = "R4"
        },
        {
          name  = "HAPI_FHIR_SUBSCRIPTION_RESTHOOK_ENABLED"
          value = "true"
        }
      ]

      secrets = [
        {
          name      = "SPRING_DATASOURCE_USERNAME"
          valueFrom = "${aws_db_instance.hapi.master_user_secret[0].secret_arn}:username::"
        },
        {
          name      = "SPRING_DATASOURCE_PASSWORD"
          valueFrom = "${aws_db_instance.hapi.master_user_secret[0].secret_arn}:password::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.hapi.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "hapi"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "hapi" {
  name            = "healthcare_realtime_hapi"
  cluster         = aws_ecs_cluster.services.id
  task_definition = aws_ecs_task_definition.hapi.arn

  desired_count = 1
  launch_type   = "FARGATE"

  platform_version = "LATEST"

  health_check_grace_period_seconds = 300

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets = var.private_subnet_ids

    security_groups = [
      aws_security_group.hapi.id
    ]

    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.hapi.arn
    container_name   = "hapi"
    container_port   = 8080
  }

  depends_on = [
    aws_lb_listener.hapi
  ]

  tags = var.tags
}
