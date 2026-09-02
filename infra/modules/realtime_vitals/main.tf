resource "aws_dynamodb_table" "latest_vitals" {
  name         = "healthcare-realtime-latest-vitals"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "patient_id"

  attribute {
    name = "patient_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}

resource "aws_dynamodb_table" "websocket_connections" {
  name         = "healthcare-realtime-websocket-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connection_id"

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