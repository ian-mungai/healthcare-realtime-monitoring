"""Install the pinned command-line tools the repository checks need into ``.tools``.

Run from the repository root: ``.venv/bin/python -m tools.install_tools``. Each binary download is checked against its
pinned SHA-256 before anything is extracted, and nothing from it runs until the check passes. checkov and SQLFluff (with
the dbt templater, dbt-core and dbt-athena) are installed into their own virtual environments so their dependencies never
touch ``.venv``; dbt-athena's pyathena range conflicts with the project pin. Idempotent: a tool whose installed version
already matches is left alone.
"""

from __future__ import annotations

import filecmp
import hashlib
import io
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from tools.process import run_command

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
TOOLS_BIN = TOOLS / "bin"

GITLEAKS_VERSION = "8.30.1"
GITLEAKS_URL = f"https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}"
# From gitleaks_8.30.1_checksums.txt on the release page, checked Sep 28 2026.
GITLEAKS_ASSETS = {
    ("Darwin", "arm64"): ("gitleaks_8.30.1_darwin_arm64.tar.gz", "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5"),
    ("Linux", "x86_64"): ("gitleaks_8.30.1_linux_x64.tar.gz", "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"),
}

TFLINT_VERSION = "0.64.0"
TFLINT_URL = f"https://github.com/terraform-linters/tflint/releases/download/v{TFLINT_VERSION}"
# From checksums.txt on the v0.64.0 release page, checked Sep 28 2026.
TFLINT_ASSETS = {
    ("Darwin", "arm64"): ("tflint_darwin_arm64.zip", "2496e9cb3d24992d553b45e7c87a0fdc9449ca975233876247a9bfeda857e6c0"),
    ("Linux", "x86_64"): ("tflint_linux_amd64.zip", "cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537"),
}

CHECKOV_VERSION = "3.3.19"

# dbt-core and dbt-athena match deploy/dbt/Dockerfile so SQLFluff compiles the models the way the dbt image runs them.
SQLFLUFF_PACKAGES = ("sqlfluff==4.3.0", "sqlfluff-templater-dbt==4.3.0", "dbt-core==1.12.3", "dbt-athena==1.11.0")


def installed_version(binary: Path, *args: str) -> str:
    """Return the tool's version output, or an empty string when it is missing or does not run."""
    if not binary.exists():
        return ""
    result = run_command(str(binary), list(args) or ["version"], timeout=60)
    return result.stdout.strip() if result.returncode == 0 else ""


def download(url: str, expected_sha256: str) -> bytes:
    """Download ``url`` and return its bytes only when they match the pinned SHA-256."""
    with tempfile.TemporaryDirectory(prefix="repo_tools_") as scratch:
        archive = Path(scratch) / "download"
        run_command("curl", ["-fsSL", "--retry", "3", "-o", str(archive), url], timeout=300, check=True)
        data = archive.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise SystemExit(f"{url}: SHA-256 {actual} does not match the pinned {expected_sha256}; nothing was installed")
    return data


def install_binary(name: str, content: bytes) -> Path:
    """Write an executable into .tools/bin and return its path."""
    TOOLS_BIN.mkdir(parents=True, exist_ok=True)
    binary = TOOLS_BIN / name
    binary.write_bytes(content)
    os.chmod(binary, 0o700)
    return binary


def pinned_asset(assets: dict[tuple[str, str], tuple[str, str]], tool: str) -> tuple[str, str]:
    """Return the (asset, checksum) pair for this machine or stop with a clear message."""
    key = (platform.system(), platform.machine())
    if key not in assets:
        raise SystemExit(f"no pinned {tool} build for {key[0]} {key[1]}; add its checksum to tools/install_tools.py")
    return assets[key]


def install_gitleaks() -> str:
    """Download, verify and install gitleaks."""
    binary = TOOLS_BIN / "gitleaks"
    if installed_version(binary) == GITLEAKS_VERSION:
        return f"unchanged  gitleaks {GITLEAKS_VERSION}"
    asset, expected = pinned_asset(GITLEAKS_ASSETS, "gitleaks")
    with tarfile.open(fileobj=io.BytesIO(download(f"{GITLEAKS_URL}/{asset}", expected)), mode="r:gz") as tar:
        member = tar.extractfile("gitleaks")
        if member is None:
            raise SystemExit(f"{asset}: no gitleaks binary in the archive")
        binary = install_binary("gitleaks", member.read())
    return f"installed  gitleaks {installed_version(binary)} ({asset}, SHA-256 verified)"


def install_tflint() -> str:
    """Download, verify and install tflint."""
    binary = TOOLS_BIN / "tflint"
    if f"TFLint version {TFLINT_VERSION}" in installed_version(binary, "--version"):
        return f"unchanged  tflint {TFLINT_VERSION}"
    asset, expected = pinned_asset(TFLINT_ASSETS, "tflint")
    with zipfile.ZipFile(io.BytesIO(download(f"{TFLINT_URL}/{asset}", expected))) as archive:
        binary = install_binary("tflint", archive.read("tflint"))
    return f"installed  tflint {TFLINT_VERSION} ({asset}, SHA-256 verified)"


def install_checkov() -> str:
    """Install the pinned checkov release into its own virtual environment under .tools."""
    environment = TOOLS / "checkov"
    binary = environment / "bin" / "checkov"
    if installed_version(binary, "--version") == CHECKOV_VERSION:
        return f"unchanged  checkov {CHECKOV_VERSION}"
    run_command(sys.executable, ["-m", "venv", "--clear", str(environment)], timeout=300, check=True)
    run_command(str(environment / "bin" / "python"), ["-m", "pip", "install", "--quiet", f"checkov=={CHECKOV_VERSION}"], timeout=900, check=True)
    TOOLS_BIN.mkdir(parents=True, exist_ok=True)
    link = TOOLS_BIN / "checkov"
    link.unlink(missing_ok=True)
    link.symlink_to(binary)
    return f"installed  checkov {installed_version(binary, '--version')} (isolated environment)"


def install_sqlfluff() -> str:
    """Install SQLFluff, its dbt templater and the pinned dbt packages into their own virtual environment under .tools.

    There is no .tools/bin link: SQLFluff runs only through tools/lint_sql.py, which keeps the dbt templater offline.
    """
    environment = TOOLS / "sqlfluff"
    python = environment / "bin" / "python"
    frozen = installed_version(python, "-m", "pip", "freeze").lower().splitlines()
    if all(package in frozen for package in SQLFLUFF_PACKAGES):
        return f"unchanged  {' '.join(SQLFLUFF_PACKAGES)}"
    run_command(sys.executable, ["-m", "venv", "--clear", str(environment)], timeout=300, check=True)
    run_command(str(python), ["-m", "pip", "install", "--quiet", *SQLFLUFF_PACKAGES], timeout=900, check=True)
    return f"installed  {' '.join(SQLFLUFF_PACKAGES)} (isolated environment)"


MARKDOWNLINT_SOURCE = ROOT / "tools" / "markdownlint"
MARKDOWNLINT_DIR = TOOLS / "markdownlint-cli2"
NODE_MAJOR_MINIMUM = 22
MARKDOWNLINT_FILES = ("package.json", "package-lock.json")


def markdownlint_current() -> bool:
    """Return whether the installed markdownlint-cli2 matches the pinned manifest and lockfile."""
    installed = MARKDOWNLINT_DIR / "node_modules" / "markdownlint-cli2" / "package.json"
    if not installed.exists():
        return False
    if not all(
        (MARKDOWNLINT_DIR / name).exists() and filecmp.cmp(MARKDOWNLINT_SOURCE / name, MARKDOWNLINT_DIR / name, shallow=False) for name in MARKDOWNLINT_FILES
    ):
        return False
    pinned = json.loads((MARKDOWNLINT_SOURCE / "package.json").read_text())["dependencies"]["markdownlint-cli2"]
    return bool(json.loads(installed.read_text())["version"] == pinned)


def install_markdownlint() -> str:
    """Install markdownlint-cli2 from the committed lockfile with npm ci; return what happened."""
    pinned = json.loads((MARKDOWNLINT_SOURCE / "package.json").read_text())["dependencies"]["markdownlint-cli2"]
    if markdownlint_current():
        return f"unchanged  markdownlint-cli2 {pinned}"
    node = run_command("node", ["--version"], timeout=30, check=True).stdout.strip()
    if int(node.lstrip("v").split(".")[0]) < NODE_MAJOR_MINIMUM:
        raise SystemExit(f"markdownlint-cli2 needs Node.js {NODE_MAJOR_MINIMUM} or later; found {node}; nothing was installed")
    MARKDOWNLINT_DIR.mkdir(parents=True, exist_ok=True)
    for name in MARKDOWNLINT_FILES:
        shutil.copyfile(MARKDOWNLINT_SOURCE / name, MARKDOWNLINT_DIR / name)
    result = run_command("npm", ["ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=MARKDOWNLINT_DIR, timeout=600)
    if result.returncode:
        for name in MARKDOWNLINT_FILES:  # A failed install must not look current on the next run.
            (MARKDOWNLINT_DIR / name).unlink(missing_ok=True)
        raise SystemExit(f"npm ci failed for markdownlint-cli2 {pinned}; nothing usable was installed:\n{result.stderr[-2000:]}")
    return f"installed  markdownlint-cli2 {pinned} (npm ci, lockfile integrity verified, Node.js {node})"


def main() -> int:
    """Install every pinned tool and report the result."""
    for installer in (install_gitleaks, install_tflint, install_checkov, install_sqlfluff, install_markdownlint):
        sys.stdout.write(installer() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
