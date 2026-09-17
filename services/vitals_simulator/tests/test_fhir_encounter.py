from datetime import UTC, datetime

import pytest

from services.vitals_simulator.app.fhir.encounter import SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, build_simulator_encounter


def test_build_simulator_encounter_links_patient_and_run():
    encounter = build_simulator_encounter("1000", "run-123", datetime(2026, 9, 17, 12, 0, tzinfo=UTC))

    assert encounter["identifier"] == [{"system": SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, "value": "run-123:1000"}]
    assert encounter["subject"]["reference"] == "Patient/1000"
    assert encounter["period"]["start"] == "2026-09-17T12:00:00+00:00"


def test_build_simulator_encounter_requires_timezone():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_simulator_encounter("1000", "run-123", datetime(2026, 9, 17, 12, 0))
