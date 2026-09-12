data "aws_iam_policy_document" "glue_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "glue" {
  name               = "healthcare_realtime_glue_role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "glue_service_role" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "glue_data_access" {
  statement {
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]

    resources = [
      "arn:aws:s3:::${var.bucket_name}/*",
    ]
  }

  statement {
    effect = "Allow"

    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]

    resources = [
      "arn:aws:s3:::${var.bucket_name}",
    ]
  }

  statement {
    effect = "Allow"

    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:CreateDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
    ]

    resources = ["*"]
  }

  dynamic "statement" {
    for_each = var.openlineage_collector_invoke_arn == "" ? [] : [var.openlineage_collector_invoke_arn]

    content {
      sid       = "PublishOpenLineageEvents"
      effect    = "Allow"
      actions   = ["execute-api:Invoke"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "glue_data_access" {
  name   = "healthcare_realtime_glue_data_access"
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.glue_data_access.json
}

resource "aws_glue_catalog_database" "healthcare_realtime" {
  name = var.database_name
}

resource "aws_glue_catalog_table" "quarantined_fhir_observations" {
  name          = "quarantined_fhir_observations"
  database_name = aws_glue_catalog_database.healthcare_realtime.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
    EXTERNAL       = "TRUE"
  }

  storage_descriptor {
    location      = var.quarantine_path
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "observation_id"
      type = "string"
    }

    columns {
      name = "patient_id"
      type = "string"
    }

    columns {
      name = "encounter_id"
      type = "string"
    }

    columns {
      name = "observation_type"
      type = "string"
    }

    columns {
      name = "loinc_code"
      type = "string"
    }

    columns {
      name = "value"
      type = "double"
    }

    columns {
      name = "unit"
      type = "string"
    }

    columns {
      name = "effective_datetime"
      type = "string"
    }

    columns {
      name = "received_at"
      type = "string"
    }

    columns {
      name = "source"
      type = "string"
    }

    columns {
      name = "rejection_reason"
      type = "string"
    }

    columns {
      name = "quarantined_at"
      type = "string"
    }
  }
}

resource "aws_s3_object" "glue_script" {
  bucket = var.bucket_name
  key    = var.script_key
  source = "${path.root}/../jobs/glue/fhir_observations_raw_to_processed.py"
  etag   = filemd5("${path.root}/../jobs/glue/fhir_observations_raw_to_processed.py")
}

resource "aws_s3_object" "glue_lineage_package" {
  bucket = var.bucket_name
  key    = "glue/dependencies/healthcare_realtime_lineage.zip"
  source = "${path.root}/../tmp/healthcare_realtime_lineage.zip"
  etag   = filemd5("${path.root}/../tmp/healthcare_realtime_lineage.zip")
}

resource "aws_glue_job" "raw_to_processed" {
  name     = var.job_name
  role_arn = aws_iam_role.glue.arn

  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 15

  command {
    name            = "glueetl"
    script_location = "s3://${var.bucket_name}/${var.script_key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                 = "python"
    "--enable-job-insights"          = "true"
    "--enable-metrics"               = "true"
    "--enable-spark-ui"              = "true"
    "--datalake-formats"             = "iceberg"
    "--RAW_PATH"                     = "s3://${var.bucket_name}/raw/fhir_observations/"
    "--DATA_BUCKET_NAME"             = var.bucket_name
    "--DATABASE_NAME"                = var.database_name
    "--TABLE_NAME"                   = "processed_fhir_observations"
    "--job-bookmark-option"          = "job-bookmark-enable"
    "--QUARANTINE_PATH"              = var.quarantine_path
    "--METRICS_PATH"                 = var.metrics_path
    "--OPENLINEAGE_URL"              = var.openlineage_collector_url
    "--extra-py-files"               = "s3://${var.bucket_name}/glue/dependencies/healthcare_realtime_lineage.zip"
    "--additional-python-modules"    = "openlineage-python[fsspec]==1.52.0,s3fs"
    "--enable-observability-metrics" = "true"
    "--conf"                         = "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.warehouse=s3://${var.bucket_name}/processed/ --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO"
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.glue_data_access,
    aws_s3_object.glue_script,
    aws_s3_object.glue_lineage_package,
  ]
}
