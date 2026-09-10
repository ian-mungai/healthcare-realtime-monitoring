import os
import sys
from datetime import UTC, datetime

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from openlineage.client.event_v2 import RunState
from pyspark.context import SparkContext
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from lineage.openlineage.glue_lineage import emit_s3_glue_lineage
from services.vital_signs import ANALYTICAL_VITAL_RANGES, FLATTENED_MEASUREMENTS, MEASUREMENT_NAMES, SUPPORTED_LOINC_CODES

RAW_CHOICE_RESOLUTION_SPECS = [
    ("heart_rate", "cast:double"),
    ("respiratory_rate", "cast:double"),
    ("spo2", "cast:double"),
    ("systolic_bp", "cast:double"),
    ("diastolic_bp", "cast:double"),
    ("observation_id", "cast:string"),
    ("patient_id", "cast:string"),
    ("event_timestamp", "cast:string"),
    ("source", "cast:string"),
]


def column_exists(df: DataFrame, field_name: str) -> bool:
    return field_name in df.columns


def create_empty_measurement_dataframe(df: DataFrame) -> DataFrame:
    return df.limit(0).select(
        F.lit(None).cast("string").alias("observation_id"),
        F.lit(None).cast("string").alias("patient_id"),
        F.lit(None).cast("string").alias("loinc_code"),
        F.lit(None).cast("double").alias("value"),
        F.lit(None).cast("string").alias("unit"),
        F.lit(None).cast("timestamp").alias("effective_datetime"),
        F.lit(None).cast("timestamp").alias("received_at"),
        F.lit(None).cast("string").alias("source"),
    )


def build_legacy_flattened_observation_id(df: DataFrame):
    source = F.col("source").cast("string") if column_exists(df, "source") else F.lit("")

    identity_fields = [
        F.coalesce(F.col("patient_id").cast("string"), F.lit("")),
        F.coalesce(F.col("event_timestamp").cast("string"), F.lit("")),
        F.coalesce(source, F.lit("")),
    ]

    for field_name in FLATTENED_MEASUREMENTS:
        if column_exists(df, field_name):
            identity_fields.append(F.coalesce(F.col(field_name).cast("string"), F.lit("")))
        else:
            identity_fields.append(F.lit(""))

    return F.concat(F.lit("legacy_flattened_"), F.sha2(F.concat_ws("|", *identity_fields), 256))


def transform_flattened_measurement(df: DataFrame, field_name: str, loinc_code: str, unit: str) -> DataFrame:
    if not column_exists(df, field_name):
        return create_empty_measurement_dataframe(df)

    observation_id = F.col("observation_id") if column_exists(df, "observation_id") else F.lit(None).cast("string")
    source = F.col("source") if column_exists(df, "source") else F.lit("fhir_webhook")
    received_at = F.to_timestamp(F.col("received_at")) if column_exists(df, "received_at") else F.to_timestamp(F.col("event_timestamp"))

    return (
        df.filter(F.col(field_name).isNotNull())
        .withColumn(
            "normalized_observation_id",
            F.when(observation_id.isNotNull() & (F.length(F.trim(observation_id)) > 0), observation_id).otherwise(build_legacy_flattened_observation_id(df)),
        )
        .select(
            F.col("normalized_observation_id").alias("observation_id"),
            F.col("patient_id").cast("string").alias("patient_id"),
            F.lit(loinc_code).alias("loinc_code"),
            F.col(field_name).cast("double").alias("value"),
            F.lit(unit).alias("unit"),
            F.to_timestamp(F.col("event_timestamp")).alias("effective_datetime"),
            received_at.alias("received_at"),
            source.cast("string").alias("source"),
        )
    )


def transform_flattened_records(df: DataFrame) -> DataFrame:
    if not column_exists(df, "patient_id") or not column_exists(df, "event_timestamp"):
        return create_empty_measurement_dataframe(df)

    measurements = create_empty_measurement_dataframe(df)

    for field_name, (loinc_code, unit) in FLATTENED_MEASUREMENTS.items():
        transformed = transform_flattened_measurement(df, field_name, loinc_code, unit)
        measurements = measurements.unionByName(transformed)

    return measurements


def build_measurement_candidates(df: DataFrame) -> DataFrame:
    return transform_flattened_records(df)


def add_measurement_metadata(df: DataFrame) -> DataFrame:
    mapping_entries = []

    for code, name in MEASUREMENT_NAMES.items():
        mapping_entries.extend([F.lit(code), F.lit(name)])

    measurement_map = F.create_map(*mapping_entries)

    return (
        df.withColumn("observation_type", measurement_map[F.col("loinc_code")])
        .withColumn("source", F.coalesce(F.col("source"), F.lit("fhir_webhook")))
        .withColumn("year", F.year("effective_datetime"))
        .withColumn("month", F.month("effective_datetime"))
        .withColumn("day", F.dayofmonth("effective_datetime"))
    )


def add_quality_result(df: DataFrame) -> DataFrame:
    range_conditions = [
        (F.col("loinc_code") == loinc_code) & F.col("value").between(*ANALYTICAL_VITAL_RANGES[field_name])
        for field_name, (loinc_code, _unit) in FLATTENED_MEASUREMENTS.items()
    ]
    range_valid = range_conditions[0]
    for condition in range_conditions[1:]:
        range_valid = range_valid | condition

    return df.withColumn(
        "rejection_reason",
        F.when(F.col("observation_id").isNull() | (F.length(F.trim(F.col("observation_id"))) == 0), F.lit("missing_observation_id"))
        .when(F.col("patient_id").isNull() | (F.length(F.trim(F.col("patient_id"))) == 0), F.lit("missing_patient_id"))
        .when(F.col("loinc_code").isNull() | (F.length(F.trim(F.col("loinc_code"))) == 0), F.lit("missing_loinc_code"))
        .when(~F.col("loinc_code").isin(SUPPORTED_LOINC_CODES), F.lit("unsupported_loinc_code"))
        .when(F.col("value").isNull(), F.lit("missing_value"))
        .when(F.col("effective_datetime").isNull(), F.lit("missing_effective_datetime"))
        .when(~range_valid, F.lit("physiological_range_violation"))
        .otherwise(F.lit(None).cast("string")),
    )


def split_quality_results(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    classified = add_quality_result(df)
    valid = classified.filter(F.col("rejection_reason").isNull()).drop("rejection_reason")
    rejected = classified.filter(F.col("rejection_reason").isNotNull())

    return valid, rejected


def select_processed_columns(df: DataFrame) -> DataFrame:
    return df.select(
        "observation_id", "patient_id", "observation_type", "loinc_code", "value", "unit", "effective_datetime", "received_at", "source", "year", "month", "day"
    )


def write_quarantine(rejected_df: DataFrame, quarantine_path: str) -> None:
    if rejected_df.limit(1).count() == 0:
        return

    output_df = rejected_df.withColumn("quarantined_at", F.current_timestamp())
    output_df.write.mode("append").json(quarantine_path)


def iceberg_table_exists(spark, database_name: str, table_name: str) -> bool:
    result = spark.sql(f"SHOW TABLES IN glue_catalog.{database_name} LIKE '{table_name}'")

    return result.count() > 0


def deduplicate_latest_records(df: DataFrame) -> DataFrame:
    latest_record = Window.partitionBy("observation_id", "loinc_code").orderBy(
        F.col("received_at").desc_nulls_last(),
        F.col("effective_datetime").desc_nulls_last(),
        F.col("source").desc_nulls_last(),
        F.col("value").desc_nulls_last(),
        F.col("patient_id").desc_nulls_last(),
        F.col("unit").desc_nulls_last(),
        F.col("observation_type").desc_nulls_last(),
    )

    return df.withColumn("_deduplication_rank", F.row_number().over(latest_record)).filter(F.col("_deduplication_rank") == 1).drop("_deduplication_rank")


def merge_processed_records(spark, valid_df: DataFrame, database_name: str, table_name: str) -> None:
    if valid_df.limit(1).count() == 0:
        return

    deduplicated_df = deduplicate_latest_records(valid_df)
    target_table = f"glue_catalog.{database_name}.{table_name}"

    if not iceberg_table_exists(spark, database_name, table_name):
        deduplicated_df.writeTo(target_table).using("iceberg").tableProperty("format-version", "2").partitionedBy(F.days("effective_datetime")).create()

        return

    deduplicated_df.createOrReplaceTempView("incoming_fhir_measurements")

    spark.sql(
        f"""
        MERGE INTO {target_table} AS target
        USING incoming_fhir_measurements AS source
        ON target.observation_id = source.observation_id
        AND target.loinc_code = source.loinc_code
        WHEN MATCHED AND (target.received_at IS NULL OR source.received_at > target.received_at) THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )


def write_metrics(spark, metrics_path: str, run_started_at: str, candidate_count: int, valid_count: int, rejected_count: int) -> None:
    metric = [
        {
            "run_started_at": run_started_at,
            "candidate_count": candidate_count,
            "valid_count": valid_count,
            "rejected_count": rejected_count,
            "processed_at": datetime.now(UTC).isoformat(),
        }
    ]

    spark.createDataFrame(metric).coalesce(1).write.mode("append").json(metrics_path)


def main():
    args = getResolvedOptions(
        sys.argv, ["JOB_NAME", "RAW_PATH", "QUARANTINE_PATH", "METRICS_PATH", "DATABASE_NAME", "TABLE_NAME", "DATA_BUCKET_NAME", "OPENLINEAGE_URL"]
    )
    run_started_at = datetime.now(UTC).isoformat()
    spark_context = SparkContext()
    glue_context = GlueContext(spark_context)
    spark = glue_context.spark_session
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)
    os.environ["DATA_BUCKET_NAME"] = args["DATA_BUCKET_NAME"]
    if args["OPENLINEAGE_URL"]:
        os.environ["OPENLINEAGE_URL"] = args["OPENLINEAGE_URL"]
    lineage_run_id = emit_s3_glue_lineage(RunState.START)

    try:
        raw_dynamic_frame = glue_context.create_dynamic_frame.from_options(
            connection_type="s3",
            connection_options={"paths": [args["RAW_PATH"]], "recurse": True},
            format="json",
            transformation_ctx="raw_fhir_observations_source",
        )

        if raw_dynamic_frame.count() == 0:
            write_metrics(spark, args["METRICS_PATH"], run_started_at, 0, 0, 0)
            job.commit()
            emit_s3_glue_lineage(RunState.COMPLETE, lineage_run_id)

            return

        resolved_raw_dynamic_frame = raw_dynamic_frame.resolveChoice(
            specs=RAW_CHOICE_RESOLUTION_SPECS, transformation_ctx="resolve_raw_fhir_observation_choices"
        )
        raw_df = resolved_raw_dynamic_frame.toDF()
        candidates_df = add_measurement_metadata(build_measurement_candidates(raw_df))
        valid_df, rejected_df = split_quality_results(candidates_df)
        valid_df = select_processed_columns(valid_df)
        candidate_count = candidates_df.count()
        valid_count = valid_df.count()
        rejected_count = rejected_df.count()

        write_quarantine(rejected_df, args["QUARANTINE_PATH"])
        merge_processed_records(spark, valid_df, args["DATABASE_NAME"], args["TABLE_NAME"])
        write_metrics(spark, args["METRICS_PATH"], run_started_at, candidate_count, valid_count, rejected_count)
        job.commit()
        emit_s3_glue_lineage(RunState.COMPLETE, lineage_run_id)

    except Exception:
        emit_s3_glue_lineage(RunState.FAIL, lineage_run_id)
        raise


if __name__ == "__main__":
    main()
