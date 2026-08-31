import io
import json

import pytest

from services.vitals_simulator.app.fhir import mapping


def build_resource_map() -> dict:
    cohort = {}
    patients = {}
    encounters = {}
    for index in range(10):
        synthea_patient_id = f"synthea-patient-{index}"
        synthea_encounter_id = f"synthea-encounter-{index}"
        hapi_patient_id = f"patient-{index}"
        hapi_encounter_id = f"encounter-{index}"
        patients[synthea_patient_id] = hapi_patient_id
        encounters[synthea_encounter_id] = hapi_encounter_id
        cohort[synthea_patient_id] = {"hapi_patient_id": hapi_patient_id, "synthea_encounter_id": synthea_encounter_id, "hapi_encounter_id": hapi_encounter_id}
    return {"patients": patients, "encounters": encounters, "cohort": cohort}


def test_load_fhir_resource_map_from_s3(monkeypatch):
    resource_map = build_resource_map()

    class FakeS3Client:
        def get_object(self, Bucket: str, Key: str) -> dict:
            assert Bucket == "healthcare-test"
            assert Key == "config/vitals_simulator/fhir_resource_map.json"
            body = io.BytesIO(json.dumps(resource_map).encode("utf-8"))
            return {"Body": body}

    monkeypatch.setenv("FHIR_RESOURCE_MAP_S3_BUCKET", "healthcare-test")
    monkeypatch.setenv("FHIR_RESOURCE_MAP_S3_KEY", "config/vitals_simulator/fhir_resource_map.json")
    monkeypatch.setattr(mapping.boto3, "client", lambda service_name: FakeS3Client())

    loaded = mapping.load_fhir_resource_map()

    assert loaded == resource_map


def test_s3_configuration_requires_bucket_and_key(monkeypatch):
    monkeypatch.setenv("FHIR_RESOURCE_MAP_S3_BUCKET", "healthcare-test")
    monkeypatch.delenv("FHIR_RESOURCE_MAP_S3_KEY", raising=False)

    with pytest.raises(RuntimeError, match="must both be configured"):
        mapping.load_fhir_resource_map()


def test_get_patient_cohort_from_s3(monkeypatch):
    resource_map = build_resource_map()

    monkeypatch.setattr(mapping, "load_fhir_resource_map", lambda: resource_map)

    cohort = mapping.get_patient_cohort()

    assert len(cohort) == 10
    assert cohort[0].hapi_patient_id == "patient-0"
    assert cohort[0].hapi_encounter_id == "encounter-0"
