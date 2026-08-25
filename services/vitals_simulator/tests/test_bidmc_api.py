from unittest.mock import patch

from fastapi.testclient import TestClient

from services.vitals_simulator.app.bidmc.api import app
from services.vitals_simulator.app.bidmc.source import VitalReading

client = TestClient(app)


SAMPLE_READINGS = [VitalReading(source_record_id="bidmc01n", offset_seconds=0, heart_rate=94.0, respiratory_rate=25.0, spo2=97.0), VitalReading(source_record_id="bidmc01n", offset_seconds=1, heart_rate=95.0, respiratory_rate=26.0, spo2=98.0)]


def test_health():
    response = client.get("/health")

    assert response.status_code == 200

    assert response.json() == {"status": "ok", "source": "PhysioNet BIDMC"}


def test_list_records():
    response = client.get("/records")

    assert response.status_code == 200

    body = response.json()

    assert body["minimum"] == 1
    assert body["maximum"] == 53
    assert "bidmc01" in body["records"]


@patch("services.vitals_simulator.app.bidmc.api.fetch_remote_bidmc_record")
def test_get_record_info(mock_fetch):
    mock_fetch.return_value = SAMPLE_READINGS

    response = client.get("/records/1")

    assert response.status_code == 200

    body = response.json()

    assert body["source_record_id"] == "bidmc01n"

    assert body["reading_count"] == 2


@patch("services.vitals_simulator.app.bidmc.api.fetch_remote_bidmc_record")
def test_get_next_reading(mock_fetch):
    mock_fetch.return_value = SAMPLE_READINGS

    client.post("/records/1/reset")

    response = client.get("/records/1/next")

    assert response.status_code == 200

    body = response.json()

    assert body["offset_seconds"] == 0
    assert body["heart_rate"] == 94.0
    assert body["spo2"] == 97.0


def test_reset():
    response = client.post("/records/1/reset")

    assert response.status_code == 200

    assert response.json() == {"record_number": 1, "position": 0}
