"""What every scenario needs: .env settings, Terraform outputs, the cohort and signed AWS clients."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import boto3
import requests
import websocket
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from e2e.report import Blocked
from scripts.infrastructure.render_project_config import load_environment_file
from scripts.synthea_loader.src.cohort import cohort_patient_ids
from tools.process import run_command

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


@dataclass
class Context:
    """Deployment settings and clients for one run."""

    env: dict[str, str]
    outputs: dict[str, Any]
    patient_ids: list[str]
    session: Any = field(repr=False)

    def output(self, name: str) -> Any:
        """A Terraform output, or Blocked naming the missing output."""
        if name not in self.outputs:
            raise Blocked(f"Terraform output {name} is missing; apply the application stage first")
        return self.outputs[name]

    def client(self, service: str) -> Any:
        return self.session.client(service)

    def signed_headers(self, url: str) -> dict[str, str]:
        """SigV4 headers for an execute-api GET (REST or WebSocket connect)."""
        signing_url = "https://" + url.removeprefix("wss://") if url.startswith("wss://") else url
        request = AWSRequest(method="GET", url=signing_url)
        credentials = self.session.get_credentials()
        if credentials is None:
            raise Blocked("no AWS credentials for the configured profile")
        SigV4Auth(credentials.get_frozen_credentials(), "execute-api", self.env["AWS_REGION"]).add_auth(request)
        return {key: str(value) for key, value in request.headers.items()}

    def get(self, url: str, signed: bool = True) -> requests.Response:
        return requests.get(url, headers=self.signed_headers(url) if signed else {}, timeout=15)

    def vitals_url(self, patient_id: str) -> str:
        return f"{str(self.output('vitals_api_endpoint')).rstrip('/')}/patients/{patient_id}/vitals"

    def websocket_url(self, patient_id: str) -> str:
        return f"{self.output('realtime_websocket_url')}?{urlencode({'patient_id': patient_id})}"


def load_context(env_file: Path) -> Context:
    """Read .env, check that infra/ points at this environment's state and read outputs and the cohort."""
    try:
        env = load_environment_file(env_file)
    except Exception as error:
        raise Blocked(f"cannot read the environment file: {error}") from None
    for name in ("AWS_PROFILE", "AWS_REGION", "TF_STATE_BUCKET"):
        if not env.get(name):
            raise Blocked(f"{name} is not set in the environment file")
    backend = INFRA / ".terraform" / "terraform.tfstate"
    selected = json.loads(backend.read_text()).get("backend", {}).get("config", {}).get("bucket") if backend.is_file() else None
    if selected != env["TF_STATE_BUCKET"]:
        raise Blocked("infra/ is not initialized for this environment's state bucket; run bootstrap.sh main-init")
    result = run_command("terraform", ["-chdir=infra", "output", "-json"], cwd=ROOT, timeout=120)
    if result.returncode:
        raise Blocked("terraform output failed; check the backend and credentials")
    outputs = {name: item.get("value") for name, item in json.loads(result.stdout or "{}").items()}
    resource_map = Path(
        os.getenv("FHIR_RESOURCE_MAP_FILE") or env.get("FHIR_RESOURCE_MAP_FILE") or ROOT / "scripts/synthea_loader/state/fhir_resource_map.json"
    )
    try:
        patient_ids = list(cohort_patient_ids(resource_map))
    except Exception:
        raise Blocked("the local FHIR resource map is missing or invalid; run run_fhir_setup.sh load") from None
    session = boto3.Session(profile_name=env["AWS_PROFILE"], region_name=env["AWS_REGION"])
    return Context(env, outputs, patient_ids, session)


class PatientListener:
    """One signed WebSocket subscription per patient, collecting message counts in background threads."""

    def __init__(self, context: Context) -> None:
        self.context = context
        self.counts = dict.fromkeys(context.patient_ids, 0)
        self.errors: dict[str, str] = {}
        self.opened: set[str] = set()
        self.lock = threading.Lock()
        self.sockets: list[websocket.WebSocketApp] = []

    def start(self, wait_seconds: float = 30.0) -> None:
        for patient_id in self.context.patient_ids:
            url = self.context.websocket_url(patient_id)
            app = websocket.WebSocketApp(
                url,
                header=[f"{k}: {v}" for k, v in self.context.signed_headers(url).items()],
                on_open=self._callback(patient_id, "open"),
                on_message=self._callback(patient_id, "message"),
                on_error=self._callback(patient_id, "error"),
            )
            self.sockets.append(app)
            threading.Thread(target=app.run_forever, daemon=True).start()
        wait_until(lambda: len(self.opened) + len(self.errors) >= len(self.context.patient_ids), wait_seconds)

    def _callback(self, patient_id: str, kind: str) -> Callable[..., None]:
        def handle(_app: websocket.WebSocketApp, payload: Any = None) -> None:
            with self.lock:
                if kind == "open":
                    self.opened.add(patient_id)
                elif kind == "error":
                    self.errors[patient_id] = type(payload).__name__
                elif kind == "message":
                    try:
                        if json.loads(payload).get("patient_id") == patient_id:
                            self.counts[patient_id] += 1
                    except (TypeError, ValueError):
                        self.errors[patient_id] = "invalid message"

        return handle

    def close(self) -> None:
        for app in self.sockets:
            app.close()


def wait_until(condition: Callable[[], bool], timeout_seconds: float, interval_seconds: float = 2.0) -> bool:
    """Poll until the condition holds or the deadline passes."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval_seconds)
    return condition()
