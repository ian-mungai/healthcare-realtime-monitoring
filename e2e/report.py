"""Run reports: one JSON and one Markdown file per scenario run, passed, failed or blocked.

Reports record checks by name with expected and observed results. Observed values are counts, statuses, timings and
patient positions (patient 1 to 10), never endpoints, account IDs, patient identifiers, secrets or signed headers.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tools.process import run_command

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "e2e"
PASSED, FAILED, NOT_RUN = "passed", "failed", "not run"


class Blocked(RuntimeError):
    """A prerequisite is missing, so the scenario could not run; the message names it without values."""


@dataclass
class Check:
    """One expectation and what was observed."""

    name: str
    expected: str
    observed: str
    status: str


@dataclass
class Report:
    """Evidence for one scenario run."""

    scenario: str
    purpose: str
    limits: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at_utc: str = field(default_factory=lambda: now())
    finished_at_utc: str = ""
    code_revision: str = ""
    uncommitted_tracked_changes: bool = False
    parameters: dict[str, object] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    evidence: dict[str, object] = field(default_factory=dict)
    status: str = ""
    error: str = ""
    reproduce: str = ""

    def check(self, name: str, expected: str, observed: str, passed: bool) -> bool:
        """Record a check and return whether it passed."""
        self.checks.append(Check(name, expected, observed, PASSED if passed else FAILED))
        return passed

    def not_run(self, name: str, expected: str, reason: str) -> None:
        """Record a check that could not run and why."""
        self.checks.append(Check(name, expected, reason, NOT_RUN))

    def finish(self, error: BaseException | None = None) -> None:
        """Set the final status: blocked for a missing prerequisite, failed for any failed check or error."""
        self.finished_at_utc = now()
        revision = run_command("git", ["rev-parse", "HEAD"], cwd=ROOT)
        self.code_revision = revision.stdout.strip() or "unknown"
        status = run_command("git", ["status", "--porcelain", "--untracked-files=no"], cwd=ROOT)
        self.uncommitted_tracked_changes = bool(status.stdout.strip())
        if isinstance(error, Blocked):
            self.status, self.error = "blocked", str(error)
        elif error is not None:
            self.status, self.error = FAILED, f"{type(error).__name__}: {error}"
        elif not self.checks or any(check.status == FAILED for check in self.checks):
            self.status = FAILED
        else:
            self.status = PASSED

    def write(self, root: Path = ARTIFACT_ROOT) -> Path:
        """Write report.json and report.md and return their folder."""
        folder = root / self.scenario / f"{self.started_at_utc.replace(':', '').replace('-', '')}_{self.run_id}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "report.json").write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        lines = [
            f"# E2E run: {self.scenario}",
            "",
            self.purpose,
            "",
            f"- Status: {self.status}",
            f"- Started (UTC): {self.started_at_utc}",
            f"- Finished (UTC): {self.finished_at_utc}",
            f"- Code revision: `{self.code_revision}` (uncommitted tracked changes: {str(self.uncommitted_tracked_changes).lower()})",
            f"- Parameters: `{json.dumps(self.parameters, sort_keys=True)}`",
        ]
        if self.error:
            lines.append(f"- Error: {self.error}")
        lines += ["", "## Checks", "", "| Check | Expected | Observed | Status |", "| --- | --- | --- | --- |"]
        lines += [f"| {c.name} | {c.expected} | {c.observed} | {c.status} |" for c in self.checks]
        if self.evidence:
            lines += ["", "## Evidence", "", "```json", json.dumps(self.evidence, indent=2, sort_keys=True), "```"]
        reproduce = self.reproduce or f"`.venv/bin/python -m e2e.run {self.scenario}` against a deployed stack."
        lines += ["", "## Reproduce", "", reproduce, ""]
        lines += ["## Limits", "", self.limits]
        (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return folder


def now() -> str:
    """Current UTC time to the second."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
