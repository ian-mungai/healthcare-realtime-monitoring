resource "aws_dynamodb_table" "latest_vitals" {
  name                        = "healthcare-realtime-latest-vitals"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "patient_id"
  deletion_protection_enabled = true

  attribute {
    name = "patient_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}

resource "aws_dynamodb_table" "processed_observations" {
  name                        = "healthcare-realtime-processed-observations"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "observation_id"
  deletion_protection_enabled = true

  attribute {
    name = "observation_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, { Purpose = "realtime-idempotency" })
}

resource "aws_dynamodb_table" "load_test_results" {
  name                        = "healthcare-realtime-load-test-results"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "observation_id"
  deletion_protection_enabled = true

  attribute {
    name = "observation_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, { Purpose = "load-testing" })
}

resource "aws_dynamodb_table" "websocket_connections" {
  name                        = "healthcare-realtime-websocket-connections"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "connection_id"
  deletion_protection_enabled = true

  attribute {
    name = "connection_id"
    type = "S"
  }

  attribute {
    name = "patient_id"
    type = "S"
  }

  global_secondary_index {
    name            = "patient_id-index"
    projection_type = "KEYS_ONLY"

    key_schema {
      attribute_name = "patient_id"
      key_type       = "HASH"
    }
  }

  tags = var.tags
}
