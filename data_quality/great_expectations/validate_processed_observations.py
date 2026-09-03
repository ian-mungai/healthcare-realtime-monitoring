import os

import great_expectations as gx
from openlineage.client.event_v2 import RunState

from lineage.openlineage.great_expectations_lineage import emit_great_expectations_lineage

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
ATHENA_DATABASE = os.getenv("ATHENA_DATABASE", "healthcare_realtime")
ATHENA_TABLE = os.getenv("ATHENA_TABLE", "processed_fhir_observations")
DATA_BUCKET_NAME = os.getenv("DATA_BUCKET_NAME", "<project-data-bucket>")
ATHENA_OUTPUT = os.getenv("ATHENA_OUTPUT", f"s3://{DATA_BUCKET_NAME}/athena_results/")

VALID_LOINC_CODES = ["8867-4", "2708-6", "8480-6", "8462-4", "9279-1"]


def build_connection_string() -> str:
    return f"awsathena+rest://@athena.{AWS_REGION}.amazonaws.com:443/{ATHENA_DATABASE}?s3_staging_dir={ATHENA_OUTPUT}"


def build_context():
    return gx.get_context(mode="ephemeral")


def build_validator(context):
    datasource = context.data_sources.add_sql(name="healthcare_realtime_athena", connection_string=build_connection_string())

    asset = datasource.add_table_asset(name="processed_fhir_observations", table_name=ATHENA_TABLE)

    batch_definition = asset.add_batch_definition_whole_table(name="processed_fhir_observations_full_table")

    batch = batch_definition.get_batch()

    suite = context.suites.add(gx.ExpectationSuite(name="processed_fhir_observations_quality"))

    validator = context.get_validator(batch=batch, expectation_suite=suite)

    return validator


def add_expectations(validator) -> None:
    validator.expect_column_values_to_not_be_null(column="observation_id")

    validator.expect_compound_columns_to_be_unique(column_list=["observation_id", "loinc_code"])

    validator.expect_column_values_to_not_be_null(column="patient_id")

    validator.expect_column_values_to_not_be_in_set(column="patient_id", value_set=[""])

    validator.expect_column_values_to_not_be_null(column="observation_type")

    validator.expect_column_values_to_not_be_null(column="loinc_code")

    validator.expect_column_values_to_be_in_set(column="loinc_code", value_set=VALID_LOINC_CODES)

    validator.expect_column_values_to_not_be_null(column="value")

    validator.expect_column_values_to_not_be_null(column="unit")

    validator.expect_column_values_to_not_be_null(column="effective_datetime")

    validator.expect_column_values_to_not_be_null(column="received_at")

    validator.expect_column_values_to_not_be_null(column="source")

    validator.expect_column_values_to_not_be_null(column="year")

    validator.expect_column_values_to_not_be_null(column="month")

    validator.expect_column_values_to_not_be_null(column="day")


def validate() -> None:
    lineage_run_id = emit_great_expectations_lineage(RunState.START)

    try:
        context = build_context()
        validator = build_validator(context)
        add_expectations(validator)

        result = validator.validate()

        print(f"Success: {result.success}")
        print(f"Evaluated expectations: {result.statistics['evaluated_expectations']}")
        print(f"Successful expectations: {result.statistics['successful_expectations']}")
        print(f"Unsuccessful expectations: {result.statistics['unsuccessful_expectations']}")
        print(f"Success percent: {result.statistics['success_percent']}")

        if not result.success:
            print("\nFailed expectations:")

            for expectation_result in result.results:
                if expectation_result.success:
                    continue

                config = expectation_result.expectation_config

                print("\n----------------------------------------")
                print(f"Expectation: {config.type}")
                print(f"Column: {config.kwargs.get('column')}")
                print(f"Arguments: {config.kwargs}")
                print(f"Result: {expectation_result.result}")

            raise RuntimeError("Processed FHIR observation data quality validation failed")

        emit_great_expectations_lineage(RunState.COMPLETE, lineage_run_id)

    except Exception:
        emit_great_expectations_lineage(RunState.FAIL, lineage_run_id)
        raise


if __name__ == "__main__":
    validate()
