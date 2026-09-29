"""Run an end-to-end scenario against the deployed stack and write its report.

Usage: python -m e2e.run realtime|access|rejection|session [--env-file PATH]

Every run writes report.json and report.md under artifacts/e2e/<scenario>/, passed, failed or blocked. ``session`` runs
the implemented scenarios in order. See docs/e2e-test-plan.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from e2e.context import ROOT, load_context
from e2e.report import Blocked, Report
from e2e.scenarios import SCENARIOS


def run(name: str, env_file: Path) -> str:
    """Run one scenario, always writing its report; return its status."""
    scenario, purpose, limits = SCENARIOS[name]
    report = Report(scenario=name, purpose=purpose, limits=limits)
    error: BaseException | None = None
    try:
        scenario(load_context(env_file), report)
    except Blocked as blocked:
        error = blocked
    except Exception as failure:
        error = failure
    report.finish(error)
    folder = report.write()
    sys.stdout.write(f"{name}: {report.status} ({folder.relative_to(ROOT)}/report.md)\n")
    return report.status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("scenario", choices=[*SCENARIOS, "session"])
    parser.add_argument("--env-file", type=Path, default=Path(os.getenv("PROJECT_ENV_FILE") or ROOT / ".env"))
    args = parser.parse_args(argv)
    names = list(SCENARIOS) if args.scenario == "session" else [args.scenario]
    statuses = [run(name, args.env_file) for name in names]
    return 0 if all(status == "passed" for status in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
