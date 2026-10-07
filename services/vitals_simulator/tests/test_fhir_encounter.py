from datetime import UTC, datetime

import pytest

from services.vitals_simulator.app.fhir.encounter import SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, SIMULATOR_SCENARIO_TAG_SYSTEM, build_simulator_encounter
from testkit import expect


def test_build_simulator_encounter_links_patient_and_run():
    encounter = build_simulator_encounter("1000", "run-123", datetime(2026, 9, 17, 12, 0, tzinfo=UTC))

    expect.equal(encounter["identifier"], [{"system": SIMULATOR_ENCOUNTER_IDENTIFIER_SYSTEM, "value": "run-123:1000"}])
    expect.equal(encounter["subject"]["reference"], "Patient/1000")
    expect.equal(encounter["period"]["start"], "2026-09-17T12:00:00+00:00")


def test_build_simulator_encounter_requires_timezone():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_simulator_encounter("1000", "run-123", datetime(2026, 9, 17, 12, 0))


def test_build_simulator_encounter_tags_the_labelled_scenario():
    started_at = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

    tagged = build_simulator_encounter("1000", "run-123", started_at, scenario="deterioration_proxy")

    expect.equal(tagged["meta"], {"tag": [{"system": SIMULATOR_SCENARIO_TAG_SYSTEM, "code": "deterioration_proxy"}]})
    expect.not_in("meta", build_simulator_encounter("1000", "run-123", started_at))


def test_a_live_encounter_is_in_progress_and_a_completed_one_is_finished():
    started_at = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

    expect.equal(build_simulator_encounter("1000", "run-123", started_at)["status"], "in-progress")
    expect.equal(build_simulator_encounter("1000", "run-123", started_at, status="finished")["status"], "finished")
