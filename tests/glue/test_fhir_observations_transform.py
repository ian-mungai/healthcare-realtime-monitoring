from pathlib import Path

GLUE_SCRIPT = Path("jobs/glue/fhir_observations_raw_to_processed.py")


def read_glue_script() -> str:
    return GLUE_SCRIPT.read_text()


def test_glue_script_exists() -> None:
    assert GLUE_SCRIPT.is_file()


def test_glue_supports_legacy_wrapped_fhir_records() -> None:
    source = read_glue_script()

    assert "resource_type" in source
    assert "payload.resourceType" in source
    assert "resource_id" in source


def test_glue_supports_flattened_vitals_records() -> None:
    source = read_glue_script()

    assert "observation_id" in source
    assert "event_timestamp" in source
    assert "heart_rate" in source
    assert "respiratory_rate" in source
    assert "spo2" in source
    assert "systolic_bp" in source
    assert "diastolic_bp" in source


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
        assert expected_spec in source


def test_glue_resolves_flattened_identity_choice_types() -> None:
    source = read_glue_script()

    expected_specs = ['("observation_id", "cast:string")', '("patient_id", "cast:string")', '("event_timestamp", "cast:string")', '("source", "cast:string")']

    for expected_spec in expected_specs:
        assert expected_spec in source


def test_glue_resolves_choice_types_before_dataframe_conversion() -> None:
    source = read_glue_script()

    resolve_position = source.index("raw_dynamic_frame.resolveChoice")
    dataframe_position = source.index("resolved_raw_dynamic_frame.toDF()")

    assert resolve_position < dataframe_position


def test_glue_uses_resolved_dynamic_frame_for_dataframe_conversion() -> None:
    source = read_glue_script()

    assert "resolved_raw_dynamic_frame = raw_dynamic_frame.resolveChoice" in source
    assert "raw_df = resolved_raw_dynamic_frame.toDF()" in source
    assert "raw_df = raw_dynamic_frame.toDF()" not in source


def test_glue_has_deterministic_legacy_identifier_strategy() -> None:
    source = read_glue_script()

    assert "sha2" in source
    assert "legacy_flattened_" in source
    assert 'column_exists(df, "source")' in source


def test_glue_preserves_measurement_merge_key() -> None:
    source = read_glue_script()

    assert 'dropDuplicates(["observation_id", "loinc_code"])' in source
    assert "target.observation_id = source.observation_id" in source
    assert "target.loinc_code = source.loinc_code" in source


def test_glue_emits_start_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    assert "lineage_run_id = emit_s3_glue_lineage(RunState.START)" in content


def test_glue_emits_complete_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    assert "emit_s3_glue_lineage(RunState.COMPLETE, lineage_run_id)" in content


def test_glue_emits_fail_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    assert "emit_s3_glue_lineage(RunState.FAIL, lineage_run_id)" in content


def test_glue_reraises_failure_after_lineage_event() -> None:
    content = GLUE_SCRIPT.read_text()

    assert "except Exception:\n        emit_s3_glue_lineage(RunState.FAIL, lineage_run_id)\n        raise" in content
