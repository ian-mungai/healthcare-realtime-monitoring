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
import time
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger("fhir_setup")

# A HAPI task that has just started answers 502 or 503 through the load balancer until its target is healthy. The wait
# stays well inside the 10-minute limit of the launcher in scripts/infrastructure/run_fhir_setup.sh.
HAPI_READY_TIMEOUT_SECONDS = 240.0
HAPI_READY_POLL_SECONDS = 10.0
HAPI_NOT_READY_STATUS_CODES = frozenset({502, 503, 504})


def required(name: str) -> str:
    """Return a required setting or stop with its name (never its value)."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def wait_for_hapi(base_url: str) -> None:
    """Wait until HAPI answers its capability statement; stop at the readiness limit or on an unexpected status."""
    deadline = time.monotonic() + HAPI_READY_TIMEOUT_SECONDS
    while True:
        try:
            response = httpx.get(f"{base_url}/metadata", headers={"Accept": "application/fhir+json"}, timeout=10.0)
        except httpx.TransportError as error:
            reason = type(error).__name__
        else:
            if response.status_code == 200:
                return
            if response.status_code not in HAPI_NOT_READY_STATUS_CODES:
                raise RuntimeError(f"HAPI FHIR metadata returned HTTP {response.status_code}")
            reason = f"HTTP {response.status_code}"
        if time.monotonic() + HAPI_READY_POLL_SECONDS > deadline:
            raise RuntimeError(f"HAPI FHIR was not ready within {HAPI_READY_TIMEOUT_SECONDS:.0f} seconds ({reason})")
        LOGGER.info("HAPI FHIR is not ready yet (%s); retrying in %.0f seconds", reason, HAPI_READY_POLL_SECONDS)
        time.sleep(HAPI_READY_POLL_SECONDS)


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
        base_url = required("FHIR_BASE_URL").rstrip("/")
        wait_for_hapi(base_url)
        resource_map = Path(scratch) / "fhir_resource_map.json"
        # The loader keeps its settings in module constants; point them at this run's HAPI and scratch copies, and put
        # them back afterwards so nothing else in the process sees the scratch folder.
        from scripts.synthea_loader.src import load_fhir as loader

        saved = (loader.FHIR_BASE_URL, loader.FHIR_OUTPUT_DIR, loader.RESOURCE_MAP_FILE)
        loader.FHIR_BASE_URL, loader.FHIR_OUTPUT_DIR, loader.RESOURCE_MAP_FILE = base_url, bundles, resource_map
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
