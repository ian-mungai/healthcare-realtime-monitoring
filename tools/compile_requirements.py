"""Compile each requirements ``.in`` source into its hash-pinned ``.txt`` lock, inside the Linux image its stage runs on.

Usage: .venv/bin/python -m tools.compile_requirements [source.in ...]   (every lock when no source is given)

Each lock is compiled with pip-tools 7.6.1 in a ``python:<version>-slim`` linux/amd64 container, the platform the
images, MWAA Serverless and Glue use, so the result does not depend on the local machine. Needs Docker and network
access to PyPI; it makes no AWS call. Recompiling an unchanged source can still pick up newer transitive releases, so
review the diff before committing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.process import run_command

ROOT = Path(__file__).resolve().parents[1]
PIP_TOOLS = "pip-tools==7.6.1"
# Source: the Python version of the runtime that installs its lock.
LOCKS = {
    "requirements_dev.in": "3.12",
    "airflow/serverless/requirements.in": "3.12",
    "airflow/serverless/requirements_dev.in": "3.12",
    "deploy/dbt/requirements.in": "3.12",
    "deploy/soda/requirements.in": "3.12",
    "services/vitals_simulator/requirements.in": "3.12",
    "jobs/glue/requirements.in": "3.11",
}
COMPILE = ["--quiet", "--generate-hashes", "--allow-unsafe", "--strip-extras", "--no-emit-index-url"]


def compile_lock(source: str) -> int:
    """Compile one source in its container and return the exit code."""
    image = f"python:{LOCKS[source]}-slim"
    output = str(Path(source).with_suffix(".txt"))
    script = f"pip install --quiet --disable-pip-version-check {PIP_TOOLS} && pip-compile {' '.join(COMPILE)} --output-file {output} {source}"
    args = ["run", "--rm", "--platform", "linux/amd64", "--volume", f"{ROOT}:/work", "--workdir", "/work", image, "bash", "-c", script]
    result = run_command("docker", args, timeout=3600, capture=False)
    sys.stdout.write(f"{'compiled' if result.returncode == 0 else 'FAILED  '} {output} ({image})\n")
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    """Compile the named sources, or every lock."""
    sources = (sys.argv[1:] if argv is None else argv) or list(LOCKS)
    unknown = [source for source in sources if source not in LOCKS]
    if unknown:
        sys.stderr.write(f"no lock is defined for: {', '.join(unknown)}; add it to LOCKS in tools/compile_requirements.py\n")
        return 2
    return max(compile_lock(source) for source in sources)


if __name__ == "__main__":
    raise SystemExit(main())
