import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

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


def transform_simple_observations(df: DataFrame) -> DataFrame:
    transformed = (
        df.withColumn("loinc_code", F.col("payload.code.coding")[0]["code"])
        .withColumn("patient_id", extract_patient_id(F.col("payload.subject.reference")))
        .withColumn("value", F.col("payload.valueQuantity.value").cast("double"))
        .withColumn("unit", F.col("payload.valueQuantity.unit"))
        .withColumn("effective_datetime", F.to_timestamp(F.col("payload.effectiveDateTime")))
        .filter(F.col("loinc_code").isin(SUPPORTED_LOINC_CODES))
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
    blood_pressure = (
        df.withColumn("parent_loinc_code", F.col("payload.code.coding")[0]["code"])
        .filter(F.col("parent_loinc_code") == "85354-9")
        .withColumn("patient_id", extract_patient_id(F.col("payload.subject.reference")))
        .withColumn("component", F.explode("payload.component"))
        .withColumn("loinc_code", F.col("component.code.coding")[0]["code"])
        .withColumn("value", F.col("component.valueQuantity.value").cast("double"))
        .withColumn("unit", F.col("component.valueQuantity.unit"))
        .withColumn("effective_datetime", F.to_timestamp(F.col("payload.effectiveDateTime")))
        .filter(F.col("loinc_code").isin("8480-6", "8462-4"))
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


def apply_quality_rules(df: DataFrame) -> DataFrame:
    required_fields_valid = (
        F.col("observation_id").isNotNull()
        & F.col("patient_id").isNotNull()
        & (F.length("patient_id") > 0)
        & F.col("loinc_code").isNotNull()
        & F.col("value").isNotNull()
        & F.col("effective_datetime").isNotNull()
    )

    physiological_range_valid = (
        ((F.col("loinc_code") == "8867-4") & F.col("value").between(20, 250))
        | ((F.col("loinc_code") == "9279-1") & F.col("value").between(4, 80))
        | ((F.col("loinc_code") == "2708-6") & F.col("value").between(50, 100))
        | ((F.col("loinc_code") == "8480-6") & F.col("value").between(50, 260))
        | ((F.col("loinc_code") == "8462-4") & F.col("value").between(30, 180))
    )

    return df.filter(required_fields_valid & physiological_range_valid)


def transform_observations(df: DataFrame) -> DataFrame:
    observations = df.filter((F.col("resource_type") == "Observation") & (F.col("payload.resourceType") == "Observation"))

    simple = transform_simple_observations(observations)
    blood_pressure = transform_blood_pressure_observations(observations)
    combined = simple.unionByName(blood_pressure)
    combined = add_measurement_metadata(combined)
    combined = apply_quality_rules(combined)

    return combined.select(
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


def main():
    args = getResolvedOptions(sys.argv, ["JOB_NAME", "RAW_PATH", "DATABASE_NAME", "TABLE_NAME"])
    spark_context = SparkContext()
    glue_context = GlueContext(spark_context)
    spark = glue_context.spark_session
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)

    raw_df = spark.read.json(args["RAW_PATH"])
    processed_df = transform_observations(raw_df)
    database_name = args["DATABASE_NAME"]
    table_name = args["TABLE_NAME"]

    spark.sql(f"CREATE DATABASE IF NOT EXISTS glue_catalog.{database_name}")
    processed_df.writeTo(f"glue_catalog.{database_name}.{table_name}").using("iceberg").tableProperty("format-version", "2").partitionedBy(F.days("effective_datetime")).createOrReplace()

    job.commit()


if __name__ == "__main__":
    main()