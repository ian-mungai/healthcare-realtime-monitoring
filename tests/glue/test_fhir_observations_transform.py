from pathlib import Path

from testkit import expect

GLUE_SCRIPT = Path("jobs/glue/fhir_observations_raw_to_processed.py")


def read_glue_script() -> str:
    return GLUE_SCRIPT.read_text()


def test_glue_script_exists() -> None:
    if not GLUE_SCRIPT.is_file():
        expect.fail("expected: GLUE_SCRIPT.is_file()")


def test_glue_excludes_retired_wrapped_fhir_records() -> None:
    source = read_glue_script()

    expect.not_in("transform_wrapped_fhir_records", source)
    expect.not_in("payload.resourceType", source)
    expect.not_in("resource_type", source)


def test_glue_supports_flattened_vitals_records() -> None:
    source = read_glue_script()

    expect.is_in("observation_id", source)
    expect.is_in("encounter_id", source)
    expect.is_in("event_timestamp", source)
    expect.is_in("heart_rate", source)
    expect.is_in("respiratory_rate", source)
    expect.is_in("spo2", source)
    expect.is_in("systolic_bp", source)
    expect.is_in("diastolic_bp", source)


def test_glue_expands_supported_loinc_codes_for_spark_isin() -> None:
    source = read_glue_script()

    expect.is_in(".isin(*SUPPORTED_LOINC_CODES)", source)
    expect.not_in(".isin(SUPPORTED_LOINC_CODES)", source)


def test_glue_resolves_flattened_measurement_choice_types() -> None:
    source = read_glue_script()

    expected_specs = [
        '("heart_rate", "cast:double")',
        '("respiratory_rate", "cast:double")',
        '("spo2", "cast:double")',
        '("systolic_bp", "cast:double")',
        '("diastolic_bp", "cast:double")',
    ]

    for expected_spec in expected_specs:
        expect.is_in(expected_spec, source)


def test_glue_resolves_flattened_identity_choice_types() -> None:
    source = read_glue_script()

    expected_specs = [
        '("observation_id", "cast:string")',
        '("patient_id", "cast:string")',
        '("encounter_id", "cast:string")',
        '("event_timestamp", "cast:string")',
        '("source", "cast:string")',
    ]

    for expected_spec in expected_specs:
        expect.is_in(expected_spec, source)


def test_glue_resolves_choice_types_before_dataframe_conversion() -> None:
    source = read_glue_script()

    resolve_position = source.index("raw_dynamic_frame.resolveChoice")
    dataframe_position = source.index("resolved_raw_dynamic_frame.toDF()")

    if not (resolve_position < dataframe_position):
        expect.fail("expected: resolve_position < dataframe_position")


def test_glue_uses_resolved_dynamic_frame_for_dataframe_conversion() -> None:
    source = read_glue_script()

    expect.is_in("resolved_raw_dynamic_frame = raw_dynamic_frame.resolveChoice", source)
    expect.is_in("raw_df = resolved_raw_dynamic_frame.toDF()", source)
    expect.not_in("raw_df = raw_dynamic_frame.toDF()", source)


def test_glue_has_deterministic_legacy_identifier_strategy() -> None:
    source = read_glue_script()

    expect.is_in("sha2", source)
    expect.is_in("legacy_flattened_", source)
    expect.is_in('column_exists(df, "source")', source)


def test_glue_preserves_measurement_merge_key() -> None:
    source = read_glue_script()

    expect.is_in('Window.partitionBy("observation_id", "loinc_code")', source)
    expect.is_in('F.col("received_at").desc_nulls_last()', source)
    expect.is_in("F.row_number().over(latest_record)", source)
    expect.is_in("target.observation_id = source.observation_id", source)
    expect.is_in("target.loinc_code = source.loinc_code", source)
    expect.is_in("target.received_at IS NULL OR source.received_at > target.received_at", source)
    expect.not_in("WHEN MATCHED THEN UPDATE SET *", source)


def test_glue_evolves_existing_iceberg_table_for_encounter_context() -> None:
    source = read_glue_script()

    expect.is_in('F.col("col_name") == "encounter_id"', source)
    expect.is_in("ALTER TABLE {target_table} ADD COLUMN encounter_id string", source)
    expect.is_in('"encounter_id",', source)


def test_glue_emits_start_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    expect.is_in("lineage_run_id = emit_s3_glue_lineage(RunState.START)", content)


def test_glue_treats_openlineage_url_as_optional() -> None:
    content = GLUE_SCRIPT.read_text()

    expect.is_in('if "--OPENLINEAGE_URL" in sys.argv:', content)
    expect.is_in('args.update(getResolvedOptions(sys.argv, ["OPENLINEAGE_URL"]))', content)
    expect.is_in('args.get("OPENLINEAGE_URL")', content)


def test_glue_emits_complete_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    expect.is_in("emit_s3_glue_lineage(RunState.COMPLETE, lineage_run_id)", content)


def test_glue_emits_fail_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    expect.is_in("emit_s3_glue_lineage(RunState.FAIL, lineage_run_id)", content)


def test_glue_reraises_failure_after_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    expect.is_in("except Exception:\n        emit_s3_glue_lineage(RunState.FAIL, lineage_run_id)\n        raise", content)
