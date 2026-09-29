"""Register a FHIR subscription once and retain a minimal private receipt without authentication headers."""

import json
import logging
import os
import re
import tempfile
from pathlib import Path

import httpx

from services.fhir_webhook.app.subscription import build_observation_subscription

OUTPUT_FILE = Path("services/fhir_webhook/output/subscription.json")
LOGGER = logging.getLogger(__name__)
ACTIVE_STATUSES = ("requested", "active")
HEADERS = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}


def receipt_from(result: object, webhook_secret: str) -> dict[str, str]:
    """Validate a Subscription resource and keep only its ID and status."""
    if not isinstance(result, dict):
        raise RuntimeError("FHIR Subscription response is not an object")
    identifier = result.get("id")
    status = result.get("status")
    if (
        result.get("resourceType") != "Subscription"
        or not isinstance(identifier, str)
        or not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", identifier)
        or webhook_secret in identifier
        or status not in ("requested", "active", "error", "off")
    ):
        raise RuntimeError("FHIR Subscription response has invalid receipt fields")
    return {"resourceType": "Subscription", "id": identifier, "status": status}


def find_existing(fhir_base_url: str, subscription: dict, webhook_secret: str) -> dict[str, str] | None:
    """Return the receipt of a requested or active Subscription with the same endpoint and criteria, if one exists."""
    try:
        response = httpx.get(
            f"{fhir_base_url.rstrip('/')}/Subscription",
            params={"url": subscription["channel"]["endpoint"], "_count": "50"},
            headers={"Accept": "application/fhir+json"},
            timeout=30.0,
        )
    except (httpx.HTTPError, httpx.InvalidURL):
        raise RuntimeError("FHIR Subscription search failed during transport") from None
    if not response.is_success:
        raise RuntimeError(f"FHIR Subscription search failed (HTTP {response.status_code})")
    try:
        bundle = response.json()
    except ValueError:
        raise RuntimeError("FHIR Subscription search response is not valid JSON") from None
    for entry in bundle.get("entry", []) if isinstance(bundle, dict) else []:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if (
            isinstance(resource, dict)
            and resource.get("criteria") == subscription["criteria"]
            and resource.get("channel", {}).get("endpoint") == subscription["channel"]["endpoint"]
            and resource.get("status") in ACTIVE_STATUSES
        ):
            return receipt_from(resource, webhook_secret)
    return None


def register(fhir_base_url: str, webhook_url: str, webhook_secret: str) -> tuple[dict[str, str], bool]:
    """Reuse a matching Subscription or create one; return the receipt and whether it was created."""
    subscription = build_observation_subscription(webhook_url, webhook_secret)
    existing = find_existing(fhir_base_url, subscription, webhook_secret)
    if existing is not None:
        return existing, False
    try:
        response = httpx.post(f"{fhir_base_url.rstrip('/')}/Subscription", headers=HEADERS, json=subscription, timeout=30.0)
    except (httpx.HTTPError, httpx.InvalidURL):
        raise RuntimeError("FHIR Subscription registration failed during transport") from None
    if not response.is_success:
        raise RuntimeError(f"FHIR Subscription registration failed (HTTP {response.status_code})")
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("FHIR Subscription response is not valid JSON") from None
    return receipt_from(result, webhook_secret), True


def main() -> None:
    """Register using environment inputs; never print or persist the returned secret or endpoint."""
    fhir_base_url = os.getenv("FHIR_BASE_URL")
    webhook_url = os.getenv("FHIR_WEBHOOK_URL")
    webhook_secret = os.getenv("FHIR_WEBHOOK_SECRET")
    if not fhir_base_url:
        raise RuntimeError("FHIR_BASE_URL is not configured")
    if not webhook_url:
        raise RuntimeError("FHIR_WEBHOOK_URL is not configured")
    if not webhook_secret:
        raise RuntimeError("FHIR_WEBHOOK_SECRET is not configured")
    receipt, created = register(fhir_base_url, webhook_url, webhook_secret)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Temporary files are owner-readable only; replacement avoids a partial receipt.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=OUTPUT_FILE.parent, delete=False) as file:
        temporary = Path(file.name)
        json.dump(receipt, file, indent=2)
        file.write("\n")
    try:
        temporary.replace(OUTPUT_FILE)
    finally:
        temporary.unlink(missing_ok=True)
    LOGGER.info("FHIR Subscription %s; private receipt: %s", "registered" if created else "already registered", OUTPUT_FILE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
