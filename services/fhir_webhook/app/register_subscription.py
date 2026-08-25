import json
import os
from pathlib import Path

import httpx

from services.fhir_webhook.app.subscription import build_observation_subscription

FHIR_BASE_URL = "https://hapi.fhir.org/baseR4"
OUTPUT_FILE = Path("services/fhir_webhook/output/subscription.json")


def main():
    webhook_url = os.getenv("FHIR_WEBHOOK_URL")
    webhook_secret = os.getenv("FHIR_WEBHOOK_SECRET")

    if not webhook_url:
        raise RuntimeError("FHIR_WEBHOOK_URL is not configured")

    if not webhook_secret:
        raise RuntimeError("FHIR_WEBHOOK_SECRET is not configured")

    subscription = build_observation_subscription(webhook_url, webhook_secret)

    response = httpx.post(f"{FHIR_BASE_URL}/Subscription", headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}, json=subscription, timeout=30.0)

    if response.is_error:
        print(f"HTTP status: {response.status_code}")
        print(response.text)
        raise RuntimeError("FHIR Subscription registration failed")

    result = response.json()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2)

    print(f"HTTP status: {response.status_code}")
    print(f"Subscription ID: {result.get('id')}")
    print(f"Subscription status: {result.get('status')}")
    print(f"Result: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
