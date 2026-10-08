resource "aws_dynamodb_table" "latest_vitals" {
  name                        = var.latest_vitals_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "patient_id"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "patient_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, { DataClassification = var.data_classification })
}

resource "aws_dynamodb_table" "processed_observations" {
  name                        = var.processed_observations_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "observation_id"
  deletion_protection_enabled = var.deletion_protection_enabled

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

  tags = merge(var.tags, { Purpose = "realtime-idempotency", DataClassification = var.data_classification })
}

resource "aws_dynamodb_table" "load_test_results" {
  name                        = var.load_test_results_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "observation_id"
  deletion_protection_enabled = var.deletion_protection_enabled

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

  tags = merge(var.tags, { Purpose = "load-testing", DataClassification = var.data_classification })
}

# The readings of each encounter's feature window, written by the stream processor and scored by the early-warning
# endpoint (services/feature_window.py). Items expire two days after they are written.
resource "aws_dynamodb_table" "feature_window" {
  name                        = var.feature_window_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "encounter_id"
  range_key                   = "reading"
  deletion_protection_enabled = var.deletion_protection_enabled

  attribute {
    name = "encounter_id"
    type = "S"
  }

  attribute {
    name = "reading"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, { Purpose = "early-warning", DataClassification = var.data_classification })
}

resource "aws_dynamodb_table" "websocket_connections" {
  name                        = var.websocket_connections_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "connection_id"
  deletion_protection_enabled = var.deletion_protection_enabled

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

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, { DataClassification = var.connections_data_classification })
}
