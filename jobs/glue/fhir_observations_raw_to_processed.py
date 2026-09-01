import sys
from datetime import UTC, datetime

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from openlineage.client.event_v2 import RunState
from pyspark.context import SparkContext
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from lineage.openlineage.glue_lineage import emit_s3_glue_lineage

MEASUREMENT_NAMES = {
    "8867-4": "heart_rate",
    "9279-1": "respiratory_rate",
    "2708-6": "spo2",
    "8480-6": "systolic_blood_pressure",
    "8462-4": "diastolic_blood_pressure",
}

FLATTENED_MEASUREMENTS = {
    "heart_rate": ("8867-4", "beats/minute"),
    "respiratory_rate": ("9279-1", "breaths/minute"),
    "spo2": ("2708-6", "%"),
    "systolic_bp": ("8480-6", "mmHg"),
    "diastolic_bp": ("8462-4", "mmHg"),
}

SUPPORTED_LOINC_CODES = list(MEASUREMENT_NAMES.keys())

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


def transform_simple_observations(df: DataFrame) -> DataFrame:
    required_fields = ("resource_id", "received_at", "payload.code", "payload.subject.reference", "payload.effectiveDateTime", "payload.valueQuantity")

    if not all(struct_field_exists(df.schema, field_path) for field_path in required_fields if field_path.startswith("payload.")):
        return create_empty_measurement_dataframe(df)

    if not column_exists(df, "resource_id") or not column_exists(df, "received_at"):
        return create_empty_measurement_dataframe(df)

    return (
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
            F.lit("fhir_webhook").alias("source"),
        )
    )


def transform_blood_pressure_observations(df: DataFrame) -> DataFrame:
    required_fields = ("payload.code", "payload.subject.reference", "payload.effectiveDateTime", "payload.component")

    if not all(struct_field_exists(df.schema, field_path) for field_path in required_fields):
        return create_empty_measurement_dataframe(df)

    if not column_exists(df, "resource_id") or not column_exists(df, "received_at"):
        return create_empty_measurement_dataframe(df)

    return (
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
            F.lit("fhir_webhook").alias("source"),
        )
    )


def transform_wrapped_fhir_records(df: DataFrame) -> DataFrame:
    if not column_exists(df, "resource_type") or not struct_field_exists(df.schema, "payload.resourceType"):
        return create_empty_measurement_dataframe(df)

    observations = df.filter((F.col("resource_type") == "Observation") & (F.col("payload.resourceType") == "Observation"))
    simple = transform_simple_observations(observations)
    blood_pressure = transform_blood_pressure_observations(observations)

    return simple.unionByName(blood_pressure)


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
    wrapped = transform_wrapped_fhir_records(df)
    flattened = transform_flattened_records(df)

    return wrapped.unionByName(flattened)


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
