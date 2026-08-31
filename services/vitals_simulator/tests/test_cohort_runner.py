from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from services.vitals_simulator.app.fhir.mapping import FHIRPatientContext
from services.vitals_simulator.app.simulation.cohort_runner import COHORT_SIZE, run_cohort_once


def build_cohort() -> list[FHIRPatientContext]:
    return [
        FHIRPatientContext(
            synthea_patient_id=f"synthea_patient_{index}",
            hapi_patient_id=f"patient_{index}",
            synthea_encounter_id=f"synthea_encounter_{index}",
            hapi_encounter_id=f"encounter_{index}",
        )
        for index in range(1, COHORT_SIZE + 1)
    ]


@patch("services.vitals_simulator.app.simulation.cohort_runner.publish_patient_event")
@patch("services.vitals_simulator.app.simulation.cohort_runner.utc_now")
@patch("services.vitals_simulator.app.simulation.cohort_runner.get_patient_cohort")
def test_run_cohort_once_publishes_all_patients(mock_get_patient_cohort, mock_utc_now, mock_publish_patient_event):
    cohort = build_cohort()
    simulation_start = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    mock_get_patient_cohort.return_value = cohort
    mock_utc_now.return_value = simulation_start
    mock_publish_patient_event.side_effect = [MagicMock(source_record_id=f"bidmc{index:02d}n", published_count=4) for index in range(1, COHORT_SIZE + 1)]

    result = run_cohort_once()

    assert len(result) == COHORT_SIZE
    mock_get_patient_cohort.assert_called_once_with(expected_count=COHORT_SIZE)
    assert mock_publish_patient_event.call_count == COHORT_SIZE
