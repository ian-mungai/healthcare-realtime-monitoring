import os
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

DEFAULT_FHIR_BASE_URL = "http://127.0.0.1:8090/fhir"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class CreatedFHIRResource:
    resource_type: str
    resource_id: str
    location: str
    status_code: int


class FHIRClientError(RuntimeError):
    pass


class FHIRRetryableError(FHIRClientError):
    pass


class FHIRPermanentError(FHIRClientError):
    pass


class HAPIFHIRClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    ):
        self.base_url = (base_url or os.getenv("FHIR_BASE_URL") or DEFAULT_FHIR_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    def post_resource(self, resource: dict) -> CreatedFHIRResource:
        resource_type = resource.get("resourceType")

        if not resource_type:
            raise ValueError("FHIR resource must contain resourceType")

        url = f"{self.base_url}/{resource_type}"
        headers = self._build_headers(resource)

        for attempt in range(1, self.max_retries + 1):
            try:
                response = httpx.post(url, headers=headers, json=resource, timeout=self.timeout_seconds)
            except httpx.RequestError as error:
                if attempt == self.max_retries:
                    raise FHIRRetryableError(f"FHIR request failed after {attempt} attempts: {error}") from error

                self._wait_before_retry(attempt)
                continue

            if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                if attempt == self.max_retries:
                    raise FHIRRetryableError(f"FHIR server returned HTTP {response.status_code} after {attempt} attempts")

                self._wait_before_retry(attempt)
                continue

            if response.is_client_error:
                raise FHIRPermanentError(self._build_error_message(response))

            if response.is_server_error:
                raise FHIRRetryableError(self._build_error_message(response))

            return self._extract_created_resource(response, resource_type)

        raise FHIRRetryableError("FHIR request failed without a response")

    def _build_headers(self, resource: dict) -> dict[str, str]:
        headers = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}

        identifiers = resource.get("identifier", [])

        if not identifiers:
            return headers

        system = identifiers[0].get("system")
        value = identifiers[0].get("value")

        if not system or not value:
            return headers

        conditional_identifier = f"{system}|{value}"
        headers["If-None-Exist"] = f"identifier={quote(conditional_identifier, safe='|:/')}"

        return headers

    def _extract_created_resource(self, response: httpx.Response, resource_type: str) -> CreatedFHIRResource:
        body = response.json()
        resource_id = body.get("id")

        if not resource_id:
            raise FHIRClientError("FHIR server response did not contain a resource ID")

        location = response.headers.get("Location") or response.headers.get("Content-Location") or f"{resource_type}/{resource_id}"

        return CreatedFHIRResource(resource_type=resource_type, resource_id=resource_id, location=location, status_code=response.status_code)

    def _build_error_message(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return f"FHIR server returned HTTP {response.status_code}: {response.text}"

        issues = body.get("issue", [])
        diagnostics = [issue.get("diagnostics") for issue in issues if issue.get("diagnostics")]

        if diagnostics:
            return f"FHIR server returned HTTP {response.status_code}: {' | '.join(diagnostics)}"

        return f"FHIR server returned HTTP {response.status_code}"

    def _wait_before_retry(self, attempt: int) -> None:
        delay = self.retry_delay_seconds * (2 ** (attempt - 1))
        time.sleep(delay)
