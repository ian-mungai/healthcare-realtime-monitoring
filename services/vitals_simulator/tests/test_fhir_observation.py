from datetime import UTC, datetime

import pytest

from services.vitals_simulator.app.bidmc.source import (
    VitalReading,
)
from services.vitals_simulator.app.fhir.observation import (
    HEART_RATE,
    RESPIRATORY_RATE,
    SPO2,
    build_effective_datetime,
    build_observations_from_reading,
    normalize_measurement,
)


def test_normalize_measurement():
    assert (
        normalize_measurement(
            24.999969557786706
        )
        == 25.0
    )

    assert (
        normalize_measurement(94.0)
        == 94.0
    )

    assert (
        normalize_measurement(None)
        is None
    )


def test_build_effective_datetime():
    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
        tzinfo=UTC,
    )

    result = build_effective_datetime(
        start,
        5,
    )

    assert result == (
        "2026-08-20T12:00:05+00:00"
    )


def test_build_effective_datetime_requires_timezone():
    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        build_effective_datetime(
            start,
            5,
        )


def test_build_three_observations():
    reading = VitalReading(
        source_record_id="bidmc01n",
        offset_seconds=2,
        heart_rate=94.0,
        respiratory_rate=(
            24.999969557786706
        ),
        spo2=97.0,
    )

    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
        tzinfo=UTC,
    )

    observations = (
        build_observations_from_reading(
            reading=reading,
            patient_id="patient_123",
            encounter_id="encounter_456",
            simulation_start=start,
        )
    )

    assert len(observations) == 3

    codes = {
        observation["code"]["coding"][0]["code"]
        for observation in observations
    }

    assert codes == {
        HEART_RATE["loinc_code"],
        RESPIRATORY_RATE["loinc_code"],
        SPO2["loinc_code"],
    }


def test_patient_reference():
    reading = VitalReading(
        source_record_id="bidmc01n",
        offset_seconds=0,
        heart_rate=94.0,
        respiratory_rate=25.0,
        spo2=97.0,
    )

    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
        tzinfo=UTC,
    )

    observations = (
        build_observations_from_reading(
            reading=reading,
            patient_id="patient_123",
            encounter_id="encounter_456",
            simulation_start=start,
        )
    )

    for observation in observations:
        assert (
            observation["subject"]["reference"]
            == "Patient/patient_123"
        )


def test_encounter_reference():
    reading = VitalReading(
        source_record_id="bidmc01n",
        offset_seconds=0,
        heart_rate=94.0,
        respiratory_rate=25.0,
        spo2=97.0,
    )

    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
        tzinfo=UTC,
    )

    observations = (
        build_observations_from_reading(
            reading=reading,
            patient_id="patient_123",
            encounter_id="encounter_456",
            simulation_start=start,
        )
    )

    for observation in observations:
        assert (
            observation["encounter"]["reference"]
            == "Encounter/encounter_456"
        )


def test_effective_datetime_uses_bidmc_offset():
    reading = VitalReading(
        source_record_id="bidmc01n",
        offset_seconds=5,
        heart_rate=94.0,
        respiratory_rate=25.0,
        spo2=97.0,
    )

    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
        tzinfo=UTC,
    )

    observations = (
        build_observations_from_reading(
            reading=reading,
            patient_id="patient_123",
            encounter_id="encounter_456",
            simulation_start=start,
        )
    )

    for observation in observations:
        assert (
            observation["effectiveDateTime"]
            == "2026-08-20T12:00:05+00:00"
        )


def test_missing_measurement_is_skipped():
    reading = VitalReading(
        source_record_id="bidmc01n",
        offset_seconds=0,
        heart_rate=94.0,
        respiratory_rate=None,
        spo2=97.0,
    )

    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
        tzinfo=UTC,
    )

    observations = (
        build_observations_from_reading(
            reading=reading,
            patient_id="patient_123",
            encounter_id="encounter_456",
            simulation_start=start,
        )
    )

    assert len(observations) == 2

    codes = {
        observation["code"]["coding"][0]["code"]
        for observation in observations
    }

    assert (
        RESPIRATORY_RATE["loinc_code"]
        not in codes
    )


def test_heart_rate_quantity():
    reading = VitalReading(
        source_record_id="bidmc01n",
        offset_seconds=0,
        heart_rate=94.0,
        respiratory_rate=None,
        spo2=None,
    )

    start = datetime(
        2026,
        8,
        20,
        12,
        0,
        0,
        tzinfo=UTC,
    )

    observations = (
        build_observations_from_reading(
            reading=reading,
            patient_id="patient_123",
            encounter_id="encounter_456",
            simulation_start=start,
        )
    )

    observation = observations[0]

    assert (
        observation["valueQuantity"]["value"]
        == 94.0
    )

    assert (
        observation["valueQuantity"]["system"]
        == "http://unitsofmeasure.org"
    )

    assert (
        observation["valueQuantity"]["code"]
        == "/min"
    )