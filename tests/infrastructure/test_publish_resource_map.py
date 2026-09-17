from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "synthea_loader" / "src" / "publish_resource_map.py"
SPEC = importlib.util.spec_from_file_location("publish_resource_map", MODULE_PATH)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def resource_map(patient_ids: list[str]) -> dict[str, object]:
    return {
        "cohort": {
            f"synthea-{index}": {"hapi_patient_id": patient_id, "synthea_encounter_id": f"synthea-encounter-{index}", "hapi_encounter_id": str(2000 + index)}
            for index, patient_id in enumerate(patient_ids)
        }
    }


def test_cohort_patient_ids_reads_and_sorts_hapi_ids(tmp_path: Path) -> None:
    path = tmp_path / "fhir_resource_map.json"
    path.write_text(json.dumps(resource_map([str(patient_id) for patient_id in range(1018, 998, -2)])), encoding="utf-8")

    assert publisher.cohort_patient_ids(path) == tuple(str(patient_id) for patient_id in range(1000, 1020, 2))


def test_cohort_patient_ids_requires_exactly_ten_unique_ids(tmp_path: Path) -> None:
    path = tmp_path / "fhir_resource_map.json"
    path.write_text(json.dumps(resource_map(["1000"] * 10)), encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        publisher.cohort_patient_ids(path)


def test_update_patient_ids_replaces_single_environment_assignment(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AWS_REGION=us-west-2\nPATIENT_IDS=old\nPROJECT_NAME=example\n", encoding="utf-8")

    publisher.update_patient_ids(path, tuple(str(patient_id) for patient_id in range(1000, 1020, 2)))

    assert path.read_text(encoding="utf-8") == ("AWS_REGION=us-west-2\nPATIENT_IDS=1000,1002,1004,1006,1008,1010,1012,1014,1016,1018\nPROJECT_NAME=example\n")
