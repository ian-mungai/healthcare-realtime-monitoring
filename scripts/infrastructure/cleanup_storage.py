from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from typing import Any

import boto3

CONFIRMATION = "delete-healthcare-realtime-development"


def chunks(items: list[dict[str, str]], size: int) -> Iterable[list[dict[str, str]]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def list_s3_object_versions(client: Any, bucket: str) -> list[dict[str, str]]:
    objects: list[dict[str, str]] = []
    paginator = client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        for field in ("Versions", "DeleteMarkers"):
            objects.extend({"Key": item["Key"], "VersionId": item["VersionId"]} for item in page.get(field, []))
    return objects


def delete_s3_object_versions(client: Any, bucket: str, objects: list[dict[str, str]]) -> None:
    for batch in chunks(objects, 1000):
        response = client.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
        if errors := response.get("Errors"):
            raise RuntimeError(f"S3 rejected {len(errors)} object-version deletions from {bucket}")


def list_ecr_images(client: Any, repository: str) -> list[dict[str, str]]:
    images: dict[str, dict[str, str]] = {}
    paginator = client.get_paginator("list_images")
    for page in paginator.paginate(repositoryName=repository, filter={"tagStatus": "ANY"}):
        for image in page.get("imageIds", []):
            if digest := image.get("imageDigest"):
                images[digest] = {"imageDigest": digest}
    return list(images.values())


def delete_ecr_images(client: Any, repository: str, images: list[dict[str, str]]) -> None:
    pending = images
    while pending:
        retryable: list[dict[str, str]] = []
        deleted_any = False
        for batch in chunks(pending, 100):
            response = client.batch_delete_image(repositoryName=repository, imageIds=batch)
            failures = response.get("failures", [])
            hard_failures = [failure for failure in failures if failure.get("failureCode") != "ImageReferencedByManifestList"]
            if hard_failures:
                raise RuntimeError(f"ECR rejected {len(hard_failures)} image deletions from {repository}")

            retryable.extend(failure["imageId"] for failure in failures)
            deleted_any = deleted_any or len(failures) < len(batch)

        if not retryable:
            return
        if not deleted_any:
            raise RuntimeError(f"ECR could not delete {len(retryable)} images still referenced by manifest lists in {repository}")
        pending = retryable


def validate_targets(buckets: list[str], protected_buckets: set[str]) -> None:
    overlap = set(buckets).intersection(protected_buckets)
    if overlap:
        raise ValueError(f"Refusing to clean protected Terraform state bucket: {sorted(overlap)[0]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or empty application S3 buckets and ECR repositories before Terraform teardown.")
    parser.add_argument("--s3-bucket", action="append", default=[], help="Versioned application bucket to inspect; repeat as needed.")
    parser.add_argument("--ecr-repository", action="append", default=[], help="Application ECR repository to inspect; repeat as needed.")
    parser.add_argument("--protected-bucket", action="append", default=[], help="Bucket that must never be emptied; repeat as needed.")
    parser.add_argument("--profile", help="Optional AWS CLI profile name.")
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"), help="AWS region.")
    parser.add_argument("--execute", action="store_true", help="Delete the listed versions and images. The default is preview only.")
    parser.add_argument("--confirm", help=f"Required with --execute; must equal {CONFIRMATION!r}.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.s3_bucket and not args.ecr_repository:
        raise SystemExit("Specify at least one --s3-bucket or --ecr-repository target")
    if args.execute and args.confirm != CONFIRMATION:
        raise SystemExit(f"--execute requires --confirm {CONFIRMATION}")

    protected_buckets = set(args.protected_bucket)
    if state_bucket := os.getenv("TF_STATE_BUCKET"):
        protected_buckets.add(state_bucket)
    try:
        validate_targets(args.s3_bucket, protected_buckets)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client("s3")
    ecr = session.client("ecr")

    for bucket in args.s3_bucket:
        objects = list_s3_object_versions(s3, bucket)
        print(f"S3 {bucket}: {len(objects)} object versions and delete markers")
        if args.execute:
            delete_s3_object_versions(s3, bucket, objects)

    for repository in args.ecr_repository:
        images = list_ecr_images(ecr, repository)
        print(f"ECR {repository}: {len(images)} images")
        if args.execute:
            delete_ecr_images(ecr, repository, images)

    print("Cleanup completed." if args.execute else "Preview only; nothing was deleted.")


if __name__ == "__main__":
    main()
