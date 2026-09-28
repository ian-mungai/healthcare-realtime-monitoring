"""Register a FHIR subscription and retain a minimal private receipt without authentication headers."""

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
    subscription = build_observation_subscription(webhook_url, webhook_secret)
    try:
        response = httpx.post(
            f"{fhir_base_url.rstrip('/')}/Subscription",
            headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"},
            json=subscription,
            timeout=30.0,
        )
    except (httpx.HTTPError, httpx.InvalidURL):
        raise RuntimeError("FHIR Subscription registration failed during transport") from None
    if not response.is_success:
        raise RuntimeError(f"FHIR Subscription registration failed (HTTP {response.status_code})")
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("FHIR Subscription response is not valid JSON") from None
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
    receipt = {"resourceType": "Subscription", "id": identifier, "status": status}
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
    LOGGER.info("FHIR Subscription registration succeeded (HTTP %s); private receipt: %s", response.status_code, OUTPUT_FILE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
