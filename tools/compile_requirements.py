"""Compile each requirements ``.in`` source into its hash-pinned ``.txt`` lock, inside the Linux image its stage runs on.

Usage: .venv/bin/python -m tools.compile_requirements [source.in ...]   (every lock when no source is given)

Each lock is compiled with pip-tools 7.6.1 in a ``python:<version>-slim`` linux/amd64 container, the platform the
images, MWAA Serverless and Glue use, so the result does not depend on the local machine. Needs Docker and network
access to PyPI; it makes no AWS call. Recompiling an unchanged source can still pick up newer transitive releases, so
review the diff before committing.

pip-compile drops a requirement whose environment marker is false in the container, such as the macOS-only appnope
that the notebook kernel needs, and pip's hash mode then refuses the lock on that platform. Each pinned requirement
with a marker in the source itself is therefore added to the lock after compiling, with every file hash PyPI lists.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

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
PYPI_RELEASE = "https://pypi.org/pypi/{name}/{version}/json"
MARKED_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;]+)\s*;\s*(.+?)\s*$")
MARKED = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)[^;]*;")
PIN_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")
COMPILE = ["--quiet", "--generate-hashes", "--allow-unsafe", "--strip-extras", "--no-emit-index-url"]


def compile_lock(source: str) -> int:
    """Compile one source in its container and return the exit code."""
    image = f"python:{LOCKS[source]}-slim"
    output = str(Path(source).with_suffix(".txt"))
    script = f"pip install --quiet --disable-pip-version-check {PIP_TOOLS} && pip-compile {' '.join(COMPILE)} --output-file {output} {source}"
    args = ["run", "--rm", "--platform", "linux/amd64", "--volume", f"{ROOT}:/work", "--workdir", "/work", image, "bash", "-c", script]
    result = run_command("docker", args, timeout=3600, capture=False)
    if result.returncode == 0:
        try:
            add_platform_pins(ROOT / source, ROOT / output)
        except LockError as error:
            sys.stderr.write(f"{error}\n")
            return 1
    sys.stdout.write(f"{'compiled' if result.returncode == 0 else 'FAILED  '} {output} ({image})\n")
    return result.returncode


class LockError(RuntimeError):
    """A platform-only pin cannot be added; the lock is left as pip-compile wrote it."""


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def marked_pins(source: Path) -> list[tuple[str, str, str]]:
    """The source's own requirements with an environment marker, as (name, version, marker)."""
    pins = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if match := MARKED_PIN.match(line):
            pins.append((match.group(1), match.group(2), match.group(3)))
        elif match := MARKED.match(line):
            raise LockError(f"{match.group(1)} in {source.name} has a marker but no single == version; a lock pin needs one")
    return pins


def release_hashes(name: str, version: str) -> list[str]:
    """Every file hash PyPI lists for the release, sorted as pip-compile writes them."""
    try:
        response = httpx.get(PYPI_RELEASE.format(name=name, version=version), timeout=30)
        response.raise_for_status()
        release = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise LockError(f"cannot read {name}=={version} from PyPI: {type(error).__name__}") from None
    if release.get("info", {}).get("yanked"):
        raise LockError(f"{name}=={version} is yanked on PyPI")
    hashes = sorted({file["digests"]["sha256"] for file in release.get("urls", [])})
    if not hashes:
        raise LockError(f"{name}=={version} has no files on PyPI")
    return hashes


def add_platform_pins(source: Path, lock: Path) -> None:
    """Add each marked pin of the source that pip-compile left out, in name order with its hashes."""
    lines = lock.read_text(encoding="utf-8").splitlines(keepends=True)
    locked = {_normalized(match.group(1)) for line in lines if (match := PIN_LINE.match(line))}
    for name, version, marker in marked_pins(source):
        if _normalized(name) in locked:
            continue
        hashes = release_hashes(name, version)
        block = [f"{name}=={version} ; {marker} \\\n"]
        block += [f"    --hash=sha256:{digest}{' \\' if number < len(hashes) - 1 else ''}\n" for number, digest in enumerate(hashes)]
        block.append(f"    # via -r {source.name}\n")
        at = next(
            (number for number, line in enumerate(lines) if (match := PIN_LINE.match(line)) and _normalized(match.group(1)) > _normalized(name)), len(lines)
        )
        lines[at:at] = block
        locked.add(_normalized(name))
    lock.write_text("".join(lines), encoding="utf-8")


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
