mock_provider "aws" {}

run "state_bucket_plan" {
  command = plan

  variables {
    aws_region                        = "example-region-1"
    state_bucket_name                 = "ci-healthcare-realtime-terraform-state"
    noncurrent_version_retention_days = 90
  }

  assert {
    condition     = aws_s3_bucket.terraform_state.force_destroy == false
    error_message = "The persistent Terraform state bucket must not allow force deletion."
  }

  assert {
    condition     = aws_s3_bucket_versioning.terraform_state.versioning_configuration[0].status == "Enabled"
    error_message = "The persistent Terraform state bucket must retain version history."
  }

  assert {
    condition     = output.main_backend_key == "terraform-state/development/terraform.tfstate"
    error_message = "The main backend key must remain stable across local and GitHub deployments."
  }
}
