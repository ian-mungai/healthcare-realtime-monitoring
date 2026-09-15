from __future__ import annotations

from typing import Any

import pytest

from scripts.infrastructure.cleanup_storage import (
    chunks,
    delete_ecr_images,
    delete_s3_object_versions,
    list_ecr_images,
    list_s3_object_versions,
    validate_targets,
)


class Paginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.pages


class Client:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_paginator(self, name: str) -> Paginator:
        self.calls.append(("get_paginator", {"name": name}))
        return Paginator(self.pages)

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_objects", kwargs))
        return {}

    def batch_delete_image(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("batch_delete_image", kwargs))
        return {}


def test_lists_versions_and_delete_markers() -> None:
    client = Client([{"Versions": [{"Key": "data.json", "VersionId": "1"}], "DeleteMarkers": [{"Key": "old.json", "VersionId": "2"}]}])

    assert list_s3_object_versions(client, "data") == [{"Key": "data.json", "VersionId": "1"}, {"Key": "old.json", "VersionId": "2"}]


def test_storage_deletes_use_aws_batch_limits() -> None:
    s3 = Client([])
    ecr = Client([])

    delete_s3_object_versions(s3, "data", [{"Key": str(index), "VersionId": "1"} for index in range(1001)])
    delete_ecr_images(ecr, "images", [{"imageDigest": str(index)} for index in range(101)])

    assert len([call for call in s3.calls if call[0] == "delete_objects"]) == 2
    assert len([call for call in ecr.calls if call[0] == "batch_delete_image"]) == 2


def test_lists_all_ecr_images() -> None:
    client = Client([{"imageIds": [{"imageDigest": "sha256:one"}]}, {"imageIds": [{"imageTag": "release"}]}])

    assert list_ecr_images(client, "images") == [{"imageDigest": "sha256:one"}, {"imageTag": "release"}]


def test_refuses_to_clean_state_bucket() -> None:
    with pytest.raises(ValueError, match="protected Terraform state bucket"):
        validate_targets(["state", "data"], {"state"})


def test_chunks_empty_input() -> None:
    assert list(chunks([], 1000)) == []
