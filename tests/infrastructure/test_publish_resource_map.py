from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from testkit import expect

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "synthea_loader" / "src" / "publish_resource_map.py"
SPEC = importlib.util.spec_from_file_location("publish_resource_map", MODULE_PATH)
if not (SPEC and SPEC.loader):
    expect.fail("expected: SPEC and SPEC.loader")
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

    expect.equal(publisher.cohort_patient_ids(path), tuple(str(patient_id) for patient_id in range(1000, 1020, 2)))


def test_cohort_patient_ids_requires_exactly_ten_unique_ids(tmp_path: Path) -> None:
    path = tmp_path / "fhir_resource_map.json"
    path.write_text(json.dumps(resource_map(["1000"] * 10)), encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        publisher.cohort_patient_ids(path)


def test_cohort_size_setting_accepts_a_one_hundred_patient_local_cohort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Local development uses 100 patients; AWS keeps the default 10.
    monkeypatch.setenv("COHORT_SIZE", "100")
    path = tmp_path / "fhir_resource_map.json"
    path.write_text(json.dumps(resource_map([f"patient-{index:03d}" for index in range(100)])), encoding="utf-8")

    expect.equal(len(publisher.cohort_patient_ids(path)), 100)


def test_cohort_size_setting_rejects_a_map_of_another_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COHORT_SIZE", "100")
    path = tmp_path / "fhir_resource_map.json"
    path.write_text(json.dumps(resource_map([str(patient_id) for patient_id in range(1000, 1010)])), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly 100 cohort entries"):
        publisher.cohort_patient_ids(path)


@pytest.mark.parametrize("value", ["0", "101", "ten", "-5"])
def test_cohort_size_setting_rejects_values_outside_one_to_one_hundred(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.synthea_loader.src.cohort import cohort_size

    monkeypatch.setenv("COHORT_SIZE", value)

    with pytest.raises(ValueError, match="COHORT_SIZE"):
        cohort_size()


def test_cohort_size_defaults_to_the_ten_patient_aws_cohort(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.synthea_loader.src.cohort import cohort_size

    monkeypatch.delenv("COHORT_SIZE", raising=False)

    expect.equal(cohort_size(), 10)


def test_environment_does_not_require_patient_ids(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("AWS_REGION=us-west-2\nPROJECT_NAME=example\n", encoding="utf-8")

    expect.equal(publisher.load_environment(path), {"AWS_REGION": "us-west-2", "PROJECT_NAME": "example"})
