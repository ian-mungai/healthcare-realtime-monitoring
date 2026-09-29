"""One-off FHIR setup task: load the synthetic cohort into HAPI FHIR or register the webhook subscription.

Usage: python -m jobs.fhir_setup.task load | register

Runs as an ECS task in the project's private subnets, so it reaches the HAPI load balancer through the NAT gateway and
no operator machine needs network access to HAPI. ``load`` downloads the Synthea bundles uploaded by
scripts/infrastructure/run_fhir_setup.sh, seeds the cohort with the existing loader and publishes the HAPI resource map.
``register`` reads the webhook secret from Secrets Manager inside AWS and registers the subscription once. Both are safe
to repeat. See docs/fhir-setup-tasks.md.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger("fhir_setup")


def required(name: str) -> str:
    """Return a required setting or stop with its name (never its value)."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def load() -> None:
    """Download the uploaded bundles, seed the cohort into HAPI and publish the resource map to S3."""
    bucket = required("FHIR_RESOURCE_MAP_S3_BUCKET")
    map_key = required("FHIR_RESOURCE_MAP_S3_KEY")
    prefix = required("SEED_BUNDLES_S3_PREFIX").rstrip("/") + "/"
    s3 = boto3.client("s3")
    with tempfile.TemporaryDirectory(prefix="fhir_setup_") as scratch:
        bundles = Path(scratch) / "fhir"
        bundles.mkdir()
        count = 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                name = item["Key"][len(prefix) :]
                if name.endswith(".json") and "/" not in name:
                    s3.download_file(bucket, item["Key"], str(bundles / name))
                    count += 1
        if not count:
            raise RuntimeError(f"no Synthea bundles under {prefix} in the data bucket; run run_fhir_setup.sh load")
        LOGGER.info("Downloaded %d Synthea bundles", count)
        resource_map = Path(scratch) / "fhir_resource_map.json"
        # The loader keeps its settings in module constants; point them at this run's HAPI and scratch copies, and put
        # them back afterwards so nothing else in the process sees the scratch folder.
        from scripts.synthea_loader.src import load_fhir as loader

        saved = (loader.FHIR_BASE_URL, loader.FHIR_OUTPUT_DIR, loader.RESOURCE_MAP_FILE)
        loader.FHIR_BASE_URL, loader.FHIR_OUTPUT_DIR, loader.RESOURCE_MAP_FILE = required("FHIR_BASE_URL").rstrip("/"), bundles, resource_map
        try:
            loader.main()
        finally:
            loader.FHIR_BASE_URL, loader.FHIR_OUTPUT_DIR, loader.RESOURCE_MAP_FILE = saved
        s3.upload_file(str(resource_map), bucket, map_key, ExtraArgs={"ServerSideEncryption": "AES256"})
        LOGGER.info("Published the HAPI resource map")


def register() -> None:
    """Register the Observation subscription with the secret read inside AWS; reuse an existing one."""
    from services.fhir_webhook.app.config import get_webhook_secret
    from services.fhir_webhook.app.register_subscription import register as register_subscription

    receipt, created = register_subscription(required("FHIR_BASE_URL"), required("FHIR_WEBHOOK_URL"), get_webhook_secret())
    LOGGER.info("FHIR Subscription %s %s (status %s)", receipt["id"], "registered" if created else "already registered", receipt["status"])


def main(argv: list[str] | None = None) -> int:
    """Run one setup command and exit non-zero with a value-free message on failure."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("command", choices=["load", "register"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        {"load": load, "register": register}[args.command]()
    except (RuntimeError, httpx.HTTPError, BotoCoreError, ClientError) as error:
        LOGGER.error("FHIR setup %s failed: %s", args.command, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
