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
