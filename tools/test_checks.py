"""E2E test of the pre-commit checks: each hook rejects a bad sample and passes a good one.

Run from the repository root after setup (``.venv`` and ``.tools`` present): ``.venv/bin/python -m tools.test_checks``.
Each case builds a scratch Git repository with this repository's hook configuration and scripts, links in ``.venv``
and ``.tools``, stages the sample and runs the hook through ``pre-commit`` itself, so a hook that is not wired in cannot
pass. Samples that look like secrets or suppressions are assembled at run time, so this file does not trip the checks it
tests. Warn-mode hooks must pass and report a warning. The CI log is the run's artifact.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from tools.process import clear_git_environment, run_command

ROOT = Path(__file__).resolve().parents[1]
PRE_COMMIT = ROOT / ".venv" / "bin" / "pre-commit"
COPIED = [".pre-commit-config.yaml", "pyproject.toml", ".env.example"]
NOQA = "no" + "qa"
TYPE_IGNORE = "type" + ": ignore"
FAKE_PAT = "gh" + "p_" + "Zx7Qm2Lp9Rt4Wv8Ks3Nd6Hy1Bc5Fj0Ga2TeQ"
ENVIRON = "os." + "environ"
ADD_ARGUMENT = "add_" + "argument"
CREDIT = "Co-Authored" + "-By"
MADE_WITH = "Generated" + " with"
SESSION = "Claude" + "-Session"
SCISSORS = "# ------------------------ >8 ------------------------"
LAUNCHER_SOURCE = (ROOT / "tools" / "process.py").read_text()
PYPROJECT = (ROOT / "pyproject.toml").read_text()


@dataclass
class Case:
    """One hook run: files to stage (or delete) in a scratch repository and the expected outcome."""

    name: str
    hook: str
    expect_pass: bool
    files: dict[str, str | bytes] = field(default_factory=dict)
    committed: dict[str, str] = field(default_factory=dict)
    delete: list[str] = field(default_factory=list)
    message: str | None = None
    expect_warning: bool = False


CASES = [
    Case("clean file", "gitleaks", True, {"notes.md": "Nothing secret here.\n"}),
    Case("GitHub token", "gitleaks", False, {"config.py": f'GITHUB = "{FAKE_PAT}"\n'}),
    Case(".env.example", "credential-files", True, {".env.example": "REGION=us-west-2\n"}),
    Case(".env", "credential-files", False, {".env": "REGION=us-west-2\n"}),
    Case("Terraform state", "credential-files", False, {"infra/terraform.tfstate": "{}\n"}),
    Case("Terraform state backup", "credential-files", False, {"infra/bootstrap/terraform.tfstate.1789700741.backup": "{}\n"}),
    Case("private key file", "credential-files", False, {"keys/deploy.pem": "placeholder\n"}),
    Case("CSV seed in a declared folder", "data-files", True, {"dbt/seeds/example.csv": "a,b\n1,2\n"}),
    Case("CSV outside declared folders", "data-files", False, {"data/patients.csv": "a,b\n1,2\n"}),
    Case("file over 5 MB", "data-files", False, {"docs/big.bin": b"\0" * (5 * 1024 * 1024 + 1)}),
    Case("file at 5 MB", "data-files", True, {"docs/ok.bin": b"\0" * (5 * 1024 * 1024)}),
    Case("approved S603 in the launcher", "suppressions", True, {"tools/process.py": LAUNCHER_SOURCE + f"x = 1  # {NOQA}: S603 - reason\n"}),
    Case("S603 outside the launcher", "suppressions", False, {"scripts/tool.py": f"x = 1  # {NOQA}: S603 - reason\n"}),
    Case("blanket noqa", "suppressions", False, {"scripts/tool.py": f"x = 1  # {NOQA}\n"}),
    Case("type ignore", "suppressions", False, {"scripts/tool.py": f"x: int = 'a'  # {TYPE_IGNORE}\n"}),
    Case("launcher import", "subprocess-imports", True, {"scripts/tool.py": "from tools.process import run_command\n"}),
    Case("subprocess import is reported", "subprocess-imports", True, {"scripts/tool.py": "import sub" + "process\n"}, expect_warning=True),
    Case("current lint settings", "lint-settings", True, {"pyproject.toml": PYPROJECT}),
    Case("Ruff rule family removed", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace(',\n    "T20"\n]', "\n]")}),
    Case("Ruff ignore added", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace("[tool.ruff.lint]\n", '[tool.ruff.lint]\nignore = ["E501"]\n')}),
    Case("Ruff line length raised", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace("line-length = 160", "line-length = 200")}),
    Case("MyPy exclude added", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace('    "^tmp/",\n', '    "^tmp/",\n    "^services/",\n')}),
    Case(
        "MyPy error code disabled",
        "lint-settings",
        False,
        {"pyproject.toml": PYPROJECT.replace("[tool.mypy]\n", '[tool.mypy]\ndisable_error_code = ["attr-defined"]\n')},
    ),
    Case("documented variable", "env-example", True, {"scripts/tool.py": "import os\n\nNAME = " + ENVIRON + '.get("AWS_REGION", "")\n'}),
    Case("undocumented variable", "env-example", False, {"scripts/tool.py": "import os\n\nNAME = " + ENVIRON + '["NEW_SETTING"]\n'}),
    Case("script removed with its docs", "removed-names", True, committed={"scripts/old_tool.py": "X = 1\n"}, delete=["scripts/old_tool.py"]),
    Case(
        "script removed, docs still name it",
        "removed-names",
        False,
        committed={"scripts/old_tool.py": "X = 1\n", "docs/guide.md": "Run `scripts/old_tool.py`.\n"},
        delete=["scripts/old_tool.py"],
    ),
    Case(
        "flag removed, docs still name it",
        "removed-names",
        False,
        committed={
            "scripts/tool.py": "import argparse\n\nP = argparse.ArgumentParser()\nP." + ADD_ARGUMENT + '("--legacy-mode")\n',
            "docs/guide.md": "Use `--legacy-mode`.\n",
        },
        files={"scripts/tool.py": "import argparse\n\nP = argparse.ArgumentParser()\n"},
    ),
    Case("typed subject with scope", "commit-msg", True, message="docs(readme): describe the data sources\n\nBody.\n"),
    Case("typed subject without scope", "commit-msg", True, message="fix: handle an empty payload\n"),
    Case("breaking change marker", "commit-msg", True, message="feat(api)!: drop the legacy route\n"),
    Case("untyped subject", "commit-msg", False, message="Update README\n"),
    Case("missing space after colon", "commit-msg", False, message="fix:handle empty input\n"),
    Case("unknown type", "commit-msg", False, message="update(readme): refresh\n"),
    Case("empty description", "commit-msg", False, message="docs(readme): \n"),
    Case("human co-author", "commit-msg", True, message=f"fix(api): handle retries\n\n{CREDIT}: Jane Doe <jane@example.invalid>\n"),
    Case("tool named without credit", "commit-msg", True, message="docs: mention editors\n\nClaude Code and Codex read the same files.\n"),
    Case("files generated with a script", "commit-msg", True, message="docs(diagram): refresh the PNG\n\nGenerated with the render script.\n"),
    Case(
        "git comments and verbose diff",
        "commit-msg",
        True,
        message=f"fix: tidy\n# {CREDIT}: Claude <x@example.invalid>\n{SCISSORS}\ndiff --git a/x b/x\n+{CREDIT}: Claude <x@example.invalid>\n",
    ),
    Case("agent credit trailer", "commit-msg", False, message=f"docs: release\n\nBody.\n\n{CREDIT}: Claude Opus 5.5 <noreply@anthropic.com>\n"),
    Case("agent credit, lower case", "commit-msg", False, message=f"fix: tidy\n\n{CREDIT.lower()}:codex <codex@example.invalid>\n"),
    Case("vendor address only", "commit-msg", False, message=f"fix: tidy\n\n{CREDIT}: Assistant <noreply@anthropic.com>\n"),
    Case("generated-with line", "commit-msg", False, message=f"fix: tidy\n\n{MADE_WITH} [Claude Code](https://claude.com/claude-code)\n"),
    Case("agent session trailer", "commit-msg", False, message=f"fix: tidy\n\n{SESSION}: https://example.invalid/session\n"),
    Case("assisted-by credit", "commit-msg", False, message="fix: tidy\n\nAssisted-By: GitHub Copilot\n"),
    Case("scissors cannot hide actual credit", "commit-msg", False, message=f"fix: tidy\n\n{SCISSORS}\n{CREDIT}: Claude\n"),
    Case("agent substring in human name", "commit-msg", True, message=f"fix: tidy\n\n{CREDIT}: Claudette Example <human@example.invalid>\n"),
]


def git(repo: Path, *args: str) -> str:
    """Run Git in the scratch repository and return its output."""
    return run_command("git", args, cwd=repo, check=True).stdout


def write(repo: Path, files: dict[str, str | bytes] | dict[str, str]) -> None:
    """Write files into the scratch repository, creating folders as needed."""
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)


def scratch_repo(root: Path, case: Case) -> Path:
    """Create a repository holding this repository's hook setup plus the case's committed files."""
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "check test")
    git(repo, "config", "user.email", "test@example.invalid")
    for relative in COPIED:
        shutil.copy(ROOT / relative, repo / relative)
    shutil.copytree(ROOT / "tools", repo / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "scripts").mkdir()
    for name in ("__init__.py", "check_commit_message.py"):
        shutil.copy(ROOT / "scripts" / name, repo / "scripts" / name)
    for tool in (".venv", ".tools"):
        (repo / tool).symlink_to(ROOT / tool)
    (repo / ".git" / "info" / "exclude").write_text(".venv\n.tools\n")
    write(repo, case.committed)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: scratch setup")
    return repo


def run_case(case: Case) -> tuple[bool, str]:
    """Run one case and return whether the hook behaved as expected, with its output."""
    with tempfile.TemporaryDirectory(prefix="repo_check_test_") as scratch:
        repo = scratch_repo(Path(scratch), case)
        write(repo, case.files)
        for relative in case.delete:
            git(repo, "rm", "-q", relative)
        git(repo, "add", "-A")
        args = ["run", case.hook]
        if case.message is not None:
            message = repo / ".git" / "COMMIT_EDITMSG"
            message.write_text(case.message)
            args += ["--hook-stage", "commit-msg", "--commit-msg-filename", str(message)]
        result = run_command(str(PRE_COMMIT), args, cwd=repo, timeout=300)
        output = result.stdout + result.stderr
        ok = (result.returncode == 0) == case.expect_pass and "Traceback (most recent call last)" not in output
        if case.expect_warning:
            ok = ok and "warning: " in output
        if case.message is not None and not case.expect_pass:
            ok = ok and any(marker in output for marker in ("subject is not a Conventional Commit", "AI attribution"))
        return ok, output


def run_range_case() -> tuple[bool, str]:
    """Exercise CI's range entry point on full stored messages, including credit after a scissors line."""
    with tempfile.TemporaryDirectory(prefix="repo_commit_range_") as scratch:
        repo = scratch_repo(Path(scratch), Case("range setup", "commit-msg", True))
        base = git(repo, "rev-parse", "HEAD").strip()
        python = str(ROOT / ".venv" / "bin" / "python")
        check = ["-m", "scripts.check_commit_message", "--range"]
        git(repo, "commit", "--allow-empty", "-qm", f"fix: human credit\n\n{CREDIT}: Jane Doe <jane@example.invalid>")
        good = run_command(python, [*check, f"{base}..HEAD"], cwd=repo)
        git(repo, "commit", "--allow-empty", "-qm", f"fix: bad credit\n\n{SCISSORS}\n{CREDIT}: Claude <noreply@anthropic.com>")
        bad = run_command(python, [*check, f"{base}..HEAD"], cwd=repo)
        missing = run_command(python, [*check, "missing-ref..HEAD"], cwd=repo)
        ok = good.returncode == 0 and bad.returncode == 1 and "AI attribution" in bad.stderr and missing.returncode != 0
        return ok, f"clean range exit={good.returncode}; attributed range exit={bad.returncode}; missing revision exit={missing.returncode}\n"


def run_hook_case() -> tuple[bool, str]:
    """Commit through the repository's .githooks so the installed hooks, not only pre-commit run, are proven."""
    with tempfile.TemporaryDirectory(prefix="repo_git_hooks_") as scratch:
        repo = scratch_repo(Path(scratch), Case("hook setup", "commit-msg", True))
        shutil.copytree(ROOT / ".githooks", repo / ".githooks")
        git(repo, "config", "core.hooksPath", ".githooks")
        write(repo, {"notes.md": "A clean change.\n"})
        git(repo, "add", "notes.md")
        good = run_command("git", ["commit", "-qm", "docs: add notes"], cwd=repo, timeout=300)
        write(repo, {"notes.md": "A second change.\n"})
        git(repo, "add", "notes.md")
        bad = run_command("git", ["commit", "-qm", f"docs: more notes\n\n{CREDIT}: Claude <noreply@anthropic.com>"], cwd=repo, timeout=300)
        write(repo, {".env": "REGION=us-west-2\n"})
        git(repo, "add", "-f", ".env")
        blocked = run_command("git", ["commit", "-qm", "chore: add env"], cwd=repo, timeout=300)
        ok = good.returncode == 0 and bad.returncode != 0 and blocked.returncode != 0
        return ok, f"clean commit exit={good.returncode}; attributed commit exit={bad.returncode}; .env commit exit={blocked.returncode}\n"


def main() -> int:
    """Run every case and report the ones whose hook did not behave as expected."""
    clear_git_environment()
    if not PRE_COMMIT.exists() or not (ROOT / ".tools" / "bin" / "gitleaks").exists():
        sys.stderr.write("setup missing: install requirements_dev.txt into .venv and run python -m tools.install_tools\n")
        return 1
    failures = 0
    for case in CASES:
        ok, output = run_case(case)
        expected = "warn" if case.expect_warning else "pass" if case.expect_pass else "block"
        sys.stdout.write(f"{'ok' if ok else 'WRONG':<6} {case.hook:<19} {case.name} (expected {expected})\n")
        if not ok:
            failures += 1
            sys.stdout.write("".join(f"       {line}\n" for line in output.strip().splitlines()[-12:]))
    count = len(CASES)
    for label, runner in (("commit-range", run_range_case), ("git hooks", run_hook_case)):
        ok, output = runner()
        count += 1
        failures += not ok
        sys.stdout.write(f"{'ok' if ok else 'WRONG':<6} {label:<19} integrated Git checks\n       {output}")
    sys.stdout.write(f"{count - failures} of {count} cases behaved as expected\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
