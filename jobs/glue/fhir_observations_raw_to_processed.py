import sys
from datetime import UTC, datetime

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

MEASUREMENT_NAMES = {
    "8867-4": "heart_rate",
    "9279-1": "respiratory_rate",
    "2708-6": "spo2",
    "8480-6": "systolic_blood_pressure",
    "8462-4": "diastolic_blood_pressure",
}

SUPPORTED_LOINC_CODES = list(MEASUREMENT_NAMES.keys())


def extract_patient_id(reference_column):
    return F.regexp_extract(reference_column, r"Patient/(.+)", 1)


def struct_field_exists(schema: StructType, field_path: str) -> bool:
    current_type = schema

    for field_name in field_path.split("."):
        if not isinstance(current_type, StructType):
            return False

        field = next((item for item in current_type.fields if item.name == field_name), None)

        if field is None:
            return False

        current_type = field.dataType

    return True


def create_empty_measurement_dataframe(df: DataFrame) -> DataFrame:
    return df.limit(0).select(
        F.lit(None).cast("string").alias("observation_id"),
        F.lit(None).cast("string").alias("patient_id"),
        F.lit(None).cast("string").alias("loinc_code"),
        F.lit(None).cast("double").alias("value"),
        F.lit(None).cast("string").alias("unit"),
        F.lit(None).cast("timestamp").alias("effective_datetime"),
        F.lit(None).cast("timestamp").alias("received_at"),
    )


def transform_simple_observations(df: DataFrame) -> DataFrame:
    if not struct_field_exists(df.schema, "payload.valueQuantity"):
        return create_empty_measurement_dataframe(df)

    transformed = (
        df.withColumn("parent_loinc_code", F.col("payload.code.coding")[0]["code"])
        .filter((F.col("parent_loinc_code") != "85354-9") | F.col("parent_loinc_code").isNull())
        .withColumn("patient_id", extract_patient_id(F.col("payload.subject.reference")))
        .withColumn("loinc_code", F.col("parent_loinc_code"))
        .withColumn("value", F.col("payload.valueQuantity.value").cast("double"))
        .withColumn("unit", F.col("payload.valueQuantity.unit"))
        .withColumn("effective_datetime", F.to_timestamp(F.col("payload.effectiveDateTime")))
        .select(
            F.col("resource_id").alias("observation_id"),
            "patient_id",
            "loinc_code",
            "value",
            "unit",
            "effective_datetime",
            F.to_timestamp("received_at").alias("received_at"),
        )
    )

    return transformed


def transform_blood_pressure_observations(df: DataFrame) -> DataFrame:
    if not struct_field_exists(df.schema, "payload.component"):
        return create_empty_measurement_dataframe(df)

    blood_pressure = (
        df.withColumn("parent_loinc_code", F.col("payload.code.coding")[0]["code"])
        .filter(F.col("parent_loinc_code") == "85354-9")
        .withColumn("patient_id", extract_patient_id(F.col("payload.subject.reference")))
        .withColumn("component", F.explode_outer("payload.component"))
        .withColumn("loinc_code", F.col("component.code.coding")[0]["code"])
        .withColumn("value", F.col("component.valueQuantity.value").cast("double"))
        .withColumn("unit", F.col("component.valueQuantity.unit"))
        .withColumn("effective_datetime", F.to_timestamp(F.col("payload.effectiveDateTime")))
        .select(
            F.col("resource_id").alias("observation_id"),
            "patient_id",
            "loinc_code",
            "value",
            "unit",
            "effective_datetime",
            F.to_timestamp("received_at").alias("received_at"),
        )
    )

    return blood_pressure


def build_measurement_candidates(df: DataFrame) -> DataFrame:
    observations = df.filter((F.col("resource_type") == "Observation") & (F.col("payload.resourceType") == "Observation"))
    simple = transform_simple_observations(observations)
    blood_pressure = transform_blood_pressure_observations(observations)

    return simple.unionByName(blood_pressure)


def add_measurement_metadata(df: DataFrame) -> DataFrame:
    mapping_entries = []

    for code, name in MEASUREMENT_NAMES.items():
        mapping_entries.extend([F.lit(code), F.lit(name)])

    measurement_map = F.create_map(*mapping_entries)

    return (
        df.withColumn("observation_type", measurement_map[F.col("loinc_code")])
        .withColumn("source", F.lit("fhir_webhook"))
        .withColumn("year", F.year("effective_datetime"))
        .withColumn("month", F.month("effective_datetime"))
        .withColumn("day", F.dayofmonth("effective_datetime"))
    )


def add_quality_result(df: DataFrame) -> DataFrame:
    range_valid = (
        ((F.col("loinc_code") == "8867-4") & F.col("value").between(20, 250))
        | ((F.col("loinc_code") == "9279-1") & F.col("value").between(4, 80))
        | ((F.col("loinc_code") == "2708-6") & F.col("value").between(50, 100))
        | ((F.col("loinc_code") == "8480-6") & F.col("value").between(50, 260))
        | ((F.col("loinc_code") == "8462-4") & F.col("value").between(30, 180))
    )

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
        "observation_id",
        "patient_id",
        "observation_type",
        "loinc_code",
        "value",
        "unit",
        "effective_datetime",
        "received_at",
        "source",
        "year",
        "month",
        "day",
    )


def write_quarantine(rejected_df: DataFrame, quarantine_path: str) -> None:
    if rejected_df.limit(1).count() == 0:
        return

    output_df = rejected_df.withColumn("quarantined_at", F.current_timestamp())
    output_df.write.mode("append").json(quarantine_path)


def iceberg_table_exists(spark, database_name: str, table_name: str) -> bool:
    result = spark.sql(f"SHOW TABLES IN glue_catalog.{database_name} LIKE '{table_name}'")

    return result.count() > 0


def merge_processed_records(spark, valid_df: DataFrame, database_name: str, table_name: str) -> None:
    if valid_df.limit(1).count() == 0:
        return

    deduplicated_df = valid_df.dropDuplicates(["observation_id", "loinc_code"])
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
        WHEN MATCHED THEN UPDATE SET *
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
    args = getResolvedOptions(sys.argv, ["JOB_NAME", "RAW_PATH", "QUARANTINE_PATH", "METRICS_PATH", "DATABASE_NAME", "TABLE_NAME"])
    run_started_at = datetime.now(UTC).isoformat()
    spark_context = SparkContext()
    glue_context = GlueContext(spark_context)
    spark = glue_context.spark_session
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)

    raw_dynamic_frame = glue_context.create_dynamic_frame.from_options(
        connection_type="s3",
        connection_options={"paths": [args["RAW_PATH"]], "recurse": True},
        format="json",
        transformation_ctx="raw_fhir_observations_source",
    )

    if raw_dynamic_frame.count() == 0:
        write_metrics(spark, args["METRICS_PATH"], run_started_at, 0, 0, 0)
        job.commit()

        return

    raw_df = raw_dynamic_frame.toDF()
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


if __name__ == "__main__":
    main()