"""Repository checks run by pre-commit and CI.

Run from the repository root: ``.venv/bin/python -m tools.repo_checks <check> [paths ...]``. Each finding names the
file and line, the policy it enforces, how to fix it and what to do when the policy seems wrong; any finding exits 1.
A check that cannot run raises and exits non-zero, so it fails closed. There are no bypasses. Markers the checks look
for are assembled from fragments, so this file does not flag itself.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tools.process import run_command

POLICY = "repository-policy"
ASK = "if the policy seems wrong for this change, stop and raise it with the repository owner; there are no bypasses"

CREDENTIAL_NAMES = (
    "*.tfstate",
    "*.tfstate.backup",
    "*.tfstate.*.backup",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials",
)
DATA_EXTENSIONS = {".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".jsonl", ".ndjson", ".avro", ".db", ".sqlite"}
DATA_FOLDERS = ("dbt/seeds/", "tests/fixtures/")  # Declared folders for synthetic seeds and fixtures only.
MAX_BYTES = 5 * 1024 * 1024

NOQA = re.compile(r"#\s*" + "no" + r"qa\b(?::\s*(?P<codes>[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*))?(?P<rest>.*)", re.IGNORECASE)
OTHER_SUPPRESSIONS = re.compile("|".join([r"#\s*type:\s*" + "ignore", "eslint" + "-disable", "@ts-" + "ignore", "@ts-" + "expect-error"]))
APPROVED_SUPPRESSIONS = {"S603": "tools/process.py"}  # Rule code: the one file allowed to carry it.
REASON = re.compile(r"^\s+-\s+\S")
LAUNCHER = "tools/process.py"
SUBPROCESS_IMPORT = re.compile(r"^\s*(?:import\s+subprocess\b|from\s+subprocess\s+import\b)", re.MULTILINE)

RUFF_SELECT = {"E", "F", "I", "B", "UP", "SIM", "T20"}  # Raise this set as rule families are enabled; never lower it.
RUFF_LINE_LENGTH = 160
RUFF_LOOSENING_KEYS = {"ignore", "extend-ignore", "per-file-ignores", "extend-per-file-ignores", "exclude", "extend-exclude", "unfixable"}
MYPY_BASELINE_EXCLUDES = {"^airflow/", "^build/", "^tmp/", "^\\.venv/", "^scripts/synthea_loader/synthea/"}
MYPY_ALLOWED_KEYS = {"python_version", "ignore_missing_imports", "explicit_package_bases", "exclude", "strict", "check_untyped_defs", "no_implicit_optional"}
MYPY_TIGHTENING_PREFIXES = ("disallow_", "warn_")
# checkov rules the repository owner accepted on 2026-09-28; the reasons are in repository-policy.
CHECKOV_ACCEPTED = {
    "CKV2_AWS_11",
    "CKV2_AWS_20",
    "CKV2_AWS_28",
    "CKV2_AWS_30",
    "CKV2_AWS_5",
    "CKV2_AWS_51",
    "CKV2_AWS_60",
    "CKV2_AWS_61",
    "CKV2_AWS_62",
    "CKV_AWS_103",
    "CKV_AWS_109",
    "CKV_AWS_111",
    "CKV_AWS_115",
    "CKV_AWS_116",
    "CKV_AWS_117",
    "CKV_AWS_118",
    "CKV_AWS_119",
    "CKV_AWS_129",
    "CKV_AWS_131",
    "CKV_AWS_136",
    "CKV_AWS_144",
    "CKV_AWS_145",
    "CKV_AWS_150",
    "CKV_AWS_157",
    "CKV_AWS_158",
    "CKV_AWS_161",
    "CKV_AWS_173",
    "CKV_AWS_18",
    "CKV_AWS_195",
    "CKV_AWS_2",
    "CKV_AWS_272",
    "CKV_AWS_293",
    "CKV_AWS_309",
    "CKV_AWS_336",
    "CKV_AWS_338",
    "CKV_AWS_353",
    "CKV_AWS_356",
    "CKV_AWS_378",
    "CKV_AWS_382",
    "CKV_AWS_394",
    "CKV_AWS_50",
    "CKV_AWS_91",
}
CHECKOV_SKIP = re.compile(r"^\s*-\s*(CKV\w+)", re.MULTILINE)

ENV_READ = re.compile(r"""(?:os\.environ(?:\.get)?\s*[\[(]\s*|os\.getenv\s*\(\s*|required_env\s*\(\s*)["']([A-Z][A-Z0-9_]*)["']""")
ENV_EXAMPLE_NAME = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)
SCRIPT_SUFFIXES = {".py", ".sh"}
FLAG = re.compile(r"""add_argument\(\s*["'](--[\w-]+)["']""")


@dataclass
class Finding:
    """One problem: where it is, what it is, the policy it breaks and how to fix it."""

    location: str
    problem: str
    rule: str
    fix: str


def git(*args: str) -> str:
    """Run Git in the current repository and return its output."""
    return run_command("git", args, check=True).stdout


def report(findings: list[Finding], *, warn: bool = False) -> int:
    """Write each finding in the fixed four-part format and return the exit code (always 0 in warn mode)."""
    label = "warning: " if warn else ""
    for finding in findings:
        sys.stderr.write(f"{label}{finding.location}: {finding.problem}\n  policy: {finding.rule}\n  fix: {finding.fix}\n  {ASK}\n")
    return 0 if warn else int(bool(findings))


def docs() -> list[Path]:
    """Return tracked Markdown files that describe current behavior; release notes are historical and exempt."""
    return [Path(p) for p in git("ls-files", "*.md").splitlines() if not Path(p).name.startswith("release-notes-")]


def mentions(name: str, files: list[Path]) -> list[str]:
    """Return ``file:line`` for every line in ``files`` that contains ``name``."""
    return [f"{file}:{number}" for file in files if file.exists() for number, line in enumerate(file.read_text().splitlines(), 1) if name in line]


def credential_files(paths: list[str]) -> list[Finding]:
    """Block environment files other than .env.example, Terraform state, keys and cloud credential files."""
    findings = []
    for path in paths:
        name = Path(path).name
        is_env = (name == ".env" or name.startswith(".env.")) and name != ".env.example"
        if is_env or any(fnmatch.fnmatch(name, pattern) for pattern in CREDENTIAL_NAMES):
            fix = "remove it from the commit (git rm --cached) and ignore it; keep secrets in AWS Secrets Manager"
            findings.append(Finding(path, "credential or state file staged", f"{POLICY}#secrets-and-credential-files", fix))
    return findings


def data_files(paths: list[str]) -> list[Finding]:
    """Block data files outside the declared folders and any file over 5 MB unless Git LFS stores it."""
    findings = []
    for path in paths:
        if Path(path).suffix.lower() in DATA_EXTENSIONS and not path.startswith(DATA_FOLDERS):
            fix = f"move synthetic or public samples into a declared folder ({', '.join(DATA_FOLDERS)}); never commit real personal data"
            findings.append(Finding(path, "data file outside the declared folders", f"{POLICY}#data-files", fix))
        if os.path.getsize(path) > MAX_BYTES and "filter: lfs" not in git("check-attr", "filter", "--", path):
            fix = "keep it out of Git (S3, a release asset) or track it with Git LFS"
            findings.append(Finding(path, f"{os.path.getsize(path):,} bytes, over the 5 MB limit", f"{POLICY}#data-files", fix))
    return findings


def suppressions(paths: list[str]) -> list[Finding]:
    """Block suppression comments except the approved rule codes in their one approved file."""
    findings = []
    for path in paths:
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            match = NOQA.search(line)
            codes = set(re.split(r"\s*,\s*", match.group("codes"))) if match and match.group("codes") else set()
            approved = (
                bool(codes) and all(APPROVED_SUPPRESSIONS.get(code) == path for code in codes) and bool(REASON.match(match.group("rest") if match else ""))
            )
            if (match and not approved) or OTHER_SUPPRESSIONS.search(line):
                fix = "fix the code so the check passes instead of suppressing it"
                findings.append(Finding(f"{path}:{number}", "suppression comment not in the approved list", f"{POLICY}#lint-and-type-settings", fix))
    return findings


def subprocess_imports(paths: list[str]) -> list[Finding]:
    """Only the process launcher may import subprocess."""
    findings = []
    for path in paths:
        if path == LAUNCHER:
            continue
        text = Path(path).read_text()
        for match in SUBPROCESS_IMPORT.finditer(text):
            number = text.count("\n", 0, match.start()) + 1
            fix = f"start programs with run_command from {LAUNCHER}"
            findings.append(Finding(f"{path}:{number}", "subprocess imported outside the process launcher", f"{POLICY}#process-launcher", fix))
    return findings


def lint_settings() -> list[Finding]:
    """Ruff keeps its rule families and line length with no ignores; MyPy settings only get stricter."""
    findings = []
    rule = f"{POLICY}#lint-and-type-settings"
    settings = tomllib.loads(Path("pyproject.toml").read_text())["tool"]
    ruff = settings.get("ruff", {})
    lint = ruff.get("lint", {})
    missing = RUFF_SELECT - set(lint.get("select", ruff.get("select", [])))
    if missing:
        findings.append(Finding("pyproject.toml", f"Ruff rule families missing from select: {', '.join(sorted(missing))}", rule, "restore them"))
    if ruff.get("line-length") != RUFF_LINE_LENGTH:
        findings.append(Finding("pyproject.toml", f"Ruff line-length is {ruff.get('line-length')}, not {RUFF_LINE_LENGTH}", rule, "restore 160"))
    loosening = sorted(RUFF_LOOSENING_KEYS & (set(ruff) | set(lint)))
    if loosening:
        findings.append(Finding("pyproject.toml", f"Ruff loosening keys present: {', '.join(loosening)}", rule, "remove them and fix the code"))
    mypy = settings.get("mypy", {})
    unexpected = sorted(key for key in mypy if key not in MYPY_ALLOWED_KEYS and not (key.startswith(MYPY_TIGHTENING_PREFIXES) and mypy[key] is True))
    if unexpected:
        findings.append(Finding("pyproject.toml", f"MyPy settings that can loosen checks: {', '.join(unexpected)}", rule, "remove them and fix the code"))
    added = sorted(set(mypy.get("exclude", [])) - MYPY_BASELINE_EXCLUDES)
    if added:
        findings.append(Finding("pyproject.toml", f"MyPy excludes added: {', '.join(added)}", rule, "type-check the code instead of excluding it"))
    if mypy.get("strict") is False:
        findings.append(Finding("pyproject.toml", "MyPy strict is switched off", rule, "remove strict = false"))
    checkov = Path(".checkov.yaml")
    unapproved = sorted(set(CHECKOV_SKIP.findall(checkov.read_text())) - CHECKOV_ACCEPTED) if checkov.exists() else []
    if unapproved:
        findings.append(
            Finding(".checkov.yaml", f"checkov rules skipped without approval: {', '.join(unapproved)}", rule, "fix the Terraform instead of skipping the rule")
        )
    return findings


def env_example() -> list[Finding]:
    """Every environment variable the Python code reads is listed in .env.example."""
    example = Path(".env.example")
    documented = set(ENV_EXAMPLE_NAME.findall(example.read_text())) if example.exists() else set()
    findings = []
    for path in git("ls-files", "*.py").splitlines():
        if path.startswith("tests/") or "/tests/" in path or Path(path).name == "conftest.py":
            continue
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            for name in ENV_READ.findall(line):
                if name not in documented:
                    fix = f"add {name}= with a comment to .env.example"
                    findings.append(Finding(f"{path}:{number}", f"{name} is read but not in .env.example", f"{POLICY}#documentation-matches-the-code", fix))
    return findings


def removed_names() -> list[Finding]:
    """A removed script, command-line flag or environment variable no longer appears in the docs."""
    base = ["diff", os.environ["PRE_COMMIT_FROM_REF"], os.environ["PRE_COMMIT_TO_REF"]] if "PRE_COMMIT_FROM_REF" in os.environ else ["diff", "--cached"]
    removed = [Path(p).name for p in git(*base, "--name-only", "--diff-filter=D").splitlines() if Path(p).suffix in SCRIPT_SUFFIXES]
    tracked_code = "\n".join(Path(p).read_text() for p in git("ls-files", "*.py").splitlines() if Path(p).exists())
    lines = [line[1:] for line in git(*base, "-U0", "--", "*.py").splitlines() if line.startswith("-") and not line.startswith("---")]
    removed += [flag for line in lines for flag in FLAG.findall(line) if flag not in set(FLAG.findall(tracked_code))]
    removed += [name for line in lines for name in ENV_READ.findall(line) if name not in set(ENV_READ.findall(tracked_code))]
    findings = []
    for name in dict.fromkeys(removed):
        for location in mentions(name, [*docs(), Path(".env.example")]):
            fix = "update or remove the text"
            findings.append(Finding(location, f"{name} was removed but is still documented", f"{POLICY}#documentation-matches-the-code", fix))
    return findings


def main() -> int:
    """Run the named check and report its findings."""
    checks = ["credential-files", "data-files", "suppressions", "subprocess-imports", "lint-settings", "env-example", "removed-names"]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("check", choices=checks)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--warn", action="store_true", help="report findings without failing (for checks not yet enforced)")
    args = parser.parse_args()
    runners: dict[str, Callable[[], list[Finding]]] = {
        "credential-files": lambda: credential_files(args.paths),
        "data-files": lambda: data_files(args.paths),
        "suppressions": lambda: suppressions(args.paths),
        "subprocess-imports": lambda: subprocess_imports(args.paths),
        "lint-settings": lint_settings,
        "env-example": env_example,
        "removed-names": removed_names,
    }
    return report(runners[args.check](), warn=args.warn)


if __name__ == "__main__":
    sys.exit(main())
