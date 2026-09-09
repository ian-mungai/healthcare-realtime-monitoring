mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["example-region-1a", "example-region-1b"]
    }
  }

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "111111111111"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_region" {
    defaults = {
      region = "example-region-1"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

mock_provider "awscc" {}

run "plan" {
  command = plan

  variables {
    aws_region                 = "example-region-1"
    data_bucket_name           = "ci-project-data-bucket"
    mwaa_source_bucket_name    = "ci-project-mwaa-source-bucket"
    realtime_alert_email       = "alerts@example.com"
    vitals_simulator_image_tag = "sha-ci"
    dbt_image_tag              = "sha-ci"
    soda_image_tag             = "sha-ci"
  }

  assert {
    condition = alltrue([
      filebase64sha256("${path.module}/../build/lambda/fhir_webhook.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/vitals_stream_processor.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/websocket_handler.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/vitals_api.zip") != "",
      filebase64sha256("${path.module}/../build/lambda/vitals_replay.zip") != "",
    ])
    error_message = "Every Lambda deployment package must produce a source code hash."
  }
}
