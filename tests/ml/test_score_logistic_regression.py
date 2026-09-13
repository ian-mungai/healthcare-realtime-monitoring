import hashlib
import io
import json
from pathlib import Path
from typing import Any

import joblib
import pytest

from jobs.ml.score_logistic_regression import load_published_model, write_predictions
from jobs.ml.train_logistic_regression import FEATURE_COLUMNS, train_baseline
from tests.ml.test_logistic_regression import sample_records


class Body:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self) -> bytes:
        return self.content


class PublishedModelClient:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        content = self.responses[Key]
        return {"Body": Body(content), "Metadata": {"sha256": hashlib.sha256(content).hexdigest()}}


def published_model_client() -> tuple[PublishedModelClient, str]:
    model, manifest = train_baseline(sample_records())
    manifest["evaluation"] = {"selected_threshold": 0.5}
    model_buffer = io.BytesIO()
    joblib.dump(model, model_buffer)
    manifest["model_sha256"] = hashlib.sha256(model_buffer.getvalue()).hexdigest()
    prefix = f"ml/model_artifacts/{manifest['model_version']}"
    responses = {f"{prefix}/manifest.json": json.dumps(manifest).encode(), f"{prefix}/model.joblib": model_buffer.getvalue()}
    return PublishedModelClient(responses), manifest["model_version"]


def test_load_published_model_verifies_version_and_feature_contract() -> None:
    client, model_version = published_model_client()

    model, manifest = load_published_model(f"s3://example-bucket/ml/model_artifacts/{model_version}", client)

    assert manifest["model_version"] == model_version
    assert model.predict_proba([[1.0] * len(FEATURE_COLUMNS)]).shape == (1, 2)


def test_load_published_model_rejects_mismatched_prefix() -> None:
    client, model_version = published_model_client()
    prefix = f"ml/model_artifacts/{model_version}"
    client.responses["ml/model_artifacts/logistic-wrong/manifest.json"] = client.responses[f"{prefix}/manifest.json"]
    client.responses["ml/model_artifacts/logistic-wrong/model.joblib"] = client.responses[f"{prefix}/model.joblib"]

    with pytest.raises(ValueError, match="does not match"):
        load_published_model("s3://example-bucket/ml/model_artifacts/logistic-wrong", client)


def test_write_predictions_creates_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "predictions.jsonl"

    write_predictions([{"model_version": "logistic-example", "predicted_label": 1}], path)

    assert json.loads(path.read_text()) == {"model_version": "logistic-example", "predicted_label": 1}
