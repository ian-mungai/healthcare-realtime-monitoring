from data_quality.great_expectations.validate_processed_observations import VALID_LOINC_CODES

EXPECTED_COLUMNS = {"observation_id", "patient_id", "observation_type", "loinc_code", "value", "unit", "effective_datetime", "received_at", "source", "year", "month", "day"}


def test_expected_processed_columns():
    assert EXPECTED_COLUMNS == {"observation_id", "patient_id", "observation_type", "loinc_code", "value", "unit", "effective_datetime", "received_at", "source", "year", "month", "day"}


def test_valid_loinc_codes():
    assert set(VALID_LOINC_CODES) == {"8867-4", "2708-6", "8480-6", "8462-4", "9279-1"}


def test_compound_uniqueness_key():
    assert ("observation_id", "loinc_code") == ("observation_id", "loinc_code")
