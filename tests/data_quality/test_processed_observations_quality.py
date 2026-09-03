from types import SimpleNamespace

from openlineage.client.event_v2 import RunState

from data_quality.great_expectations import validate_processed_observations
from data_quality.great_expectations.validate_processed_observations import VALID_LOINC_CODES

EXPECTED_COLUMNS = {
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
}


def test_expected_processed_columns():
    assert EXPECTED_COLUMNS == {
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
    }


def test_valid_loinc_codes():
    assert set(VALID_LOINC_CODES) == {"8867-4", "2708-6", "8480-6", "8462-4", "9279-1"}


def test_compound_uniqueness_key():
    assert ("observation_id", "loinc_code") == ("observation_id", "loinc_code")


def test_validate_runs_suite_once_and_emits_complete_lineage(monkeypatch):
    validation_result = SimpleNamespace(
        success=True,
        statistics={
            "evaluated_expectations": 15,
            "successful_expectations": 15,
            "unsuccessful_expectations": 0,
            "success_percent": 100.0,
        },
        results=[],
    )
    validate_calls = 0

    def validate_once():
        nonlocal validate_calls
        validate_calls += 1
        return validation_result

    validator = SimpleNamespace(validate=validate_once)
    lineage_calls = []

    monkeypatch.setattr(validate_processed_observations, "build_context", lambda: object())
    monkeypatch.setattr(validate_processed_observations, "build_validator", lambda context: validator)
    monkeypatch.setattr(validate_processed_observations, "add_expectations", lambda current_validator: None)
    monkeypatch.setattr(
        validate_processed_observations,
        "emit_great_expectations_lineage",
        lambda state, run_id=None: lineage_calls.append((state, run_id)) or "quality-run-id",
    )

    validate_processed_observations.validate()

    assert validate_calls == 1
    assert lineage_calls == [
        (RunState.START, None),
        (RunState.COMPLETE, "quality-run-id"),
    ]
