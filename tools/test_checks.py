"""E2E test of the pre-commit checks: each hook rejects a bad sample with its expected diagnostic and passes a good one.

Run from the repository root after setup (``.venv`` and ``.tools`` present): ``.venv/bin/python -m tools.test_checks``.
Each case builds a scratch Git repository with this repository's hook configuration and scripts, links in ``.venv``
and ``.tools``, stages the sample and runs the hook through ``pre-commit`` itself, so a hook that is not wired in cannot
pass. Samples that look like secrets or suppressions are assembled at run time, so this file does not trip the checks it
tests. A rejection counts only when the output cites its declared reason in BLOCK_REASONS; warn-mode hooks must pass and
report that same reason as a warning. The CI log is the run's artifact.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from tools.process import clear_git_environment, run_command

ROOT = Path(__file__).resolve().parents[1]
PRE_COMMIT = ROOT / ".venv" / "bin" / "pre-commit"
COPIED = [".pre-commit-config.yaml", "pyproject.toml", ".env.example", ".checkov.yaml", ".sqlfluff", ".markdownlint-cli2.jsonc"]
NOQA = "no" + "qa"
TYPE_IGNORE = "type" + ": ignore"
FAKE_PAT = "gh" + "p_" + "Zx7Qm2Lp9Rt4Wv8Ks3Nd6Hy1Bc5Fj0Ga2TeQ"
ENVIRON = "os." + "environ"
ADD_ARGUMENT = "add_" + "argument"
CREDIT = "Co-Authored" + "-By"
MADE_WITH = "Generated" + " with"
SESSION = "Claude" + "-Session"
SCISSORS = "# ------------------------ >8 ------------------------"
VENDOR_ADDRESS = "noreply" + "@" + "anthropic.com"  # The attribution check matches this vendor address.
# Privacy samples are assembled so this file does not trip the privacy scan it tests.
HOME_PATH = "/Us" + "ers/jdoe/projects/app/run.log"
TEMP_PATH = "/var/" + "folders/zq/k3j9x0000gn/T/run_1"
PERSONAL_EMAIL = "jane.doe" + "@" + "gmail.com"
PHONE = "(206) 555" + "-0100"
AWS_ARN = "arn:aws:iam::" + "1234" + "56789012" + ":role/deploy"
ENV_VALUE = "acme" + "-admin-profile"
ALLOWLIST = ".privacy_allowlist"
CLEANUP_ALLOWLIST = ".cleanup_allowlist"
# Removed and unused names are assembled so this file, copied into each scratch repository, never references them.
OLD_TOOL = "old_" + "tool"
OLD_FUNCTION = "build_" + "report"
OLD_VARIABLE = "legacy_" + "bucket"
OLD_MODEL = "old_" + "model"
OLD_TASK = "load_" + "vitals"
UNUSED_FUNCTION = "never_called_" + "helper"
UNUSED_SETTING = "LEGACY_" + "SETTING"
ORPHAN_DOC = "docs/forgotten" + ".md"
LAUNCHER_SOURCE = (ROOT / "tools" / "process.py").read_text()
PYPROJECT = (ROOT / "pyproject.toml").read_text()
CHECKOV_CONFIG = (ROOT / ".checkov.yaml").read_text()
OPEN_SSH_GROUP = """resource "aws_security_group" "open" {
  description = "sample"
  ingress {
    description = "sample"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
"""
SQL_PROJECT = {
    "dbt/dbt_project.yml": 'name: sample\nversion: "1.0.0"\nconfig-version: 2\nprofile: healthcare_realtime\nmodel-paths:\n  - models\n',
    "deploy/dbt/profiles.yml": (ROOT / "deploy" / "dbt" / "profiles.yml").read_text(),
}
SQLFLUFF_CONFIG = (ROOT / ".sqlfluff").read_text()
TERRAFORM_VERSIONS = 'terraform {\n  required_version = ">= 1.11"\n}\n\n'


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
    Case("subprocess import", "subprocess-imports", False, {"scripts/tool.py": "import sub" + "process\n"}),
    Case("current lint settings", "lint-settings", True, {"pyproject.toml": PYPROJECT}),
    Case("Ruff rule family removed", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace(',\n    "S"\n]', "\n]")}),
    Case("Ruff ignore added", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace("[tool.ruff.lint]\n", '[tool.ruff.lint]\nignore = ["E501"]\n')}),
    Case("Ruff line length raised", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace("line-length = 160", "line-length = 200")}),
    Case("MyPy exclude added", "lint-settings", False, {"pyproject.toml": PYPROJECT.replace('    "^tmp/",\n', '    "^tmp/",\n    "^services/",\n')}),
    Case(
        "MyPy error code disabled",
        "lint-settings",
        False,
        {"pyproject.toml": PYPROJECT.replace("[tool.mypy]\n", '[tool.mypy]\ndisable_error_code = ["attr-defined"]\n')},
    ),
    Case("versioned Terraform", "tflint", True, {"infra/main.tf": TERRAFORM_VERSIONS + 'output "region" {\n  value = "us-west-2"\n}\n'}),
    Case("unused Terraform variable", "tflint", False, {"infra/main.tf": TERRAFORM_VERSIONS + 'variable "unused" {\n  type = string\n}\n'}),
    Case("Terraform without findings", "checkov", True, {"infra/main.tf": 'output "region" {\n  value = "us-west-2"\n}\n'}),
    Case("SSH open to the internet", "checkov", False, {"infra/main.tf": OPEN_SSH_GROUP}),
    Case("styled dbt model", "sqlfluff", True, {"dbt/models/sample.sql": "select\n    1 as sample_id,\n    'a' as sample_code\n"}, committed=SQL_PROJECT),
    Case("upper-case SQL keywords", "sqlfluff", False, {"dbt/models/sample.sql": "SELECT\n    1 AS sample_id\n"}, committed=SQL_PROJECT),
    Case("SQL noqa comment", "suppressions", False, {"dbt/models/sample.sql": "select 1 as sample_id  -- " + NOQA + "\n"}),
    Case("SQLFluff rule excluded", "lint-settings", False, {".sqlfluff": SQLFLUFF_CONFIG.replace("[sqlfluff]\n", "[sqlfluff]\nexclude_rules = LT02\n")}),
    Case("SQLFluff templater changed", "lint-settings", False, {".sqlfluff": SQLFLUFF_CONFIG.replace("templater = dbt", "templater = jinja")}),
    Case("checkov skip added", "lint-settings", False, {".checkov.yaml": CHECKOV_CONFIG + "  - CKV_AWS_24  # sample\n"}),
    Case("clean privacy sample", "privacy-scan", True, {"notes.md": "Ask someone@example.invalid; logs live under ~/app.\n"}),
    Case("home path", "privacy-scan", False, {"notes.md": f"Log at {HOME_PATH}\n"}),
    Case("temp path", "privacy-scan", False, {"notes.md": f"Scratch at {TEMP_PATH}\n"}),
    Case("personal email", "privacy-scan", False, {"notes.md": f"Ask {PERSONAL_EMAIL}\n"}),
    Case("phone number", "privacy-scan", False, {"notes.md": f"Call {PHONE}\n"}),
    Case("AWS account ARN", "privacy-scan", False, {"infra/policy.json": f'{{"Resource": "{AWS_ARN}"}}\n'}),
    Case("value declared in .env", "privacy-scan", False, {".env": f"AWS_PROFILE={ENV_VALUE}\n", "scripts/deploy.sh": f"aws s3 ls --profile {ENV_VALUE}\n"}),
    Case(
        "profile named after the project",
        "privacy-scan",
        True,
        {".env": "PROJECT_NAME=acme-portal-monitoring\nAWS_PROFILE=acme_portal\n", "infra/names.tf": 'locals {\n  prefix = "acme_portal"\n}\n'},
    ),
    Case(
        "bucket named after the project",
        "privacy-scan",
        False,
        {
            ".env": "PROJECT_NAME=acme-portal-monitoring\nDATA_BUCKET_NAME=acme-portal-monitoring-data-17\n",
            "docs/notes.md": "Data lives in acme-portal-monitoring-data-17.\n",
        },
    ),
    Case("allowlisted email", "privacy-scan", True, {"notes.md": f"Ask {PERSONAL_EMAIL}\n", ALLOWLIST: "email notes.md -- synthetic contact used in a demo\n"}),
    Case("allowlist entry without reason", "privacy-scan", False, {"notes.md": "Nothing here.\n", ALLOWLIST: "email notes.md\n"}),
    Case("documented variable", "env-example", True, {"scripts/tool.py": "import os\n\nNAME = " + ENVIRON + '.get("AWS_REGION", "")\n'}),
    Case("undocumented variable", "env-example", False, {"scripts/tool.py": "import os\n\nNAME = " + ENVIRON + '["NEW_SETTING"]\n'}),
    Case("script removed with its docs", "removed-names", True, committed={f"scripts/{OLD_TOOL}.py": "X = 1\n"}, delete=[f"scripts/{OLD_TOOL}.py"]),
    Case(
        "script removed, docs still name it",
        "removed-names",
        False,
        committed={f"scripts/{OLD_TOOL}.py": "X = 1\n", "docs/guide.md": f"Run `scripts/{OLD_TOOL}.py`.\n"},
        delete=[f"scripts/{OLD_TOOL}.py"],
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
    Case("agent credit trailer", "commit-msg", False, message=f"docs: release\n\nBody.\n\n{CREDIT}: Claude Opus 5.5 <{VENDOR_ADDRESS}>\n"),
    Case("agent credit, lower case", "commit-msg", False, message=f"fix: tidy\n\n{CREDIT.lower()}:codex <codex@example.invalid>\n"),
    Case("vendor address only", "commit-msg", False, message=f"fix: tidy\n\n{CREDIT}: Assistant <{VENDOR_ADDRESS}>\n"),
    Case("generated-with line", "commit-msg", False, message=f"fix: tidy\n\n{MADE_WITH} [Claude Code](https://claude.com/claude-code)\n"),
    Case("agent session trailer", "commit-msg", False, message=f"fix: tidy\n\n{SESSION}: https://example.invalid/session\n"),
    Case("assisted-by credit", "commit-msg", False, message="fix: tidy\n\nAssisted-By: GitHub Copilot\n"),
    Case("scissors cannot hide actual credit", "commit-msg", False, message=f"fix: tidy\n\n{SCISSORS}\n{CREDIT}: Claude\n"),
    Case("agent substring in human name", "commit-msg", True, message=f"fix: tidy\n\n{CREDIT}: Claudette Example <human@example.invalid>\n"),
]

# The diagnostic each rejection must cite, so a hook that fails for an unrelated reason cannot pass as a block.
GOOD_DOC = "---\ntitle: Guide\ndescription: Read the setup guide.\nlast_updated: 2026-10-02\n---\n\n# Guide\n\nFor operators configuring the service.\n"
CASES.extend(
    [
        Case("valid document metadata", "front-matter", True, {"docs/guide.md": GOOD_DOC}),
        Case("missing document metadata", "front-matter", False, {"docs/guide.md": "# Guide\n"}),
        Case("metadata title mismatch", "front-matter", False, {"docs/guide.md": GOOD_DOC.replace("title: Guide", "title: Other")}),
        Case("invalid metadata date", "front-matter", False, {"docs/guide.md": GOOD_DOC.replace("2026-10-02", "2026-99-99")}),
        Case("metadata timestamp rejected", "front-matter", False, {"docs/guide.md": GOOD_DOC.replace("2026-10-02", "2026-10-02T12:00:00Z")}),
        Case("README-like guide metadata", "front-matter", False, {"docs/README_policy.md": "# Policy\n"}),
        Case("nested writing code exemption", "writing-check", True, {"docs/guide.md": GOOD_DOC + "\n````markdown\n```text\nA, B, and C.\n```\n````\n"}),
        Case("README metadata exemption", "front-matter", True, {"README.md": "# Project\n"}),
        Case("writing code exemption", "writing-check", True, {"docs/guide.md": GOOD_DOC + "\n```text\nA, and B on 2026-10-02.\n```\n"}),
        Case("writing conjunction", "writing-check", False, {"docs/guide.md": GOOD_DOC + "\nA, B, and C.\n"}),
        Case("writing time word", "writing-check", False, {"docs/guide.md": GOOD_DOC + "\nIt currently runs.\n"}),
        Case("clean Markdown", "markdownlint", True, {"docs/guide.md": GOOD_DOC}),
        Case(
            "function removed, code still calls it",
            "removed-names",
            False,
            committed={
                "scripts/helpers.py": f"def {OLD_FUNCTION}() -> int:\n    return 1\n",
                "scripts/use.py": f"from scripts.helpers import {OLD_FUNCTION}\n",
            },
            files={"scripts/helpers.py": "X = 1\n"},
        ),
        Case(
            "removed reference allowlisted",
            "removed-names",
            True,
            committed={
                "scripts/helpers.py": f"def {OLD_FUNCTION}() -> int:\n    return 1\n",
                "scripts/use.py": f"from scripts.helpers import {OLD_FUNCTION}\n",
            },
            files={"scripts/helpers.py": "X = 1\n", CLEANUP_ALLOWLIST: "python scripts/use.py -- sample: the test asserts the old name is gone\n"},
        ),
        Case("cleanup allowlist entry without reason", "removed-names", False, files={CLEANUP_ALLOWLIST: "python scripts/use.py\n"}),
        Case(
            "Terraform variable removed, still referenced",
            "removed-names",
            False,
            committed={
                "infra/variables.tf": f'variable "{OLD_VARIABLE}" {{\n  type = string\n}}\n',
                "infra/main.tf": f"locals {{\n  b = var.{OLD_VARIABLE}\n}}\n",
            },
            files={"infra/variables.tf": ""},
        ),
        Case(
            "dbt model removed, still referenced",
            "removed-names",
            False,
            committed={
                f"dbt/models/{OLD_MODEL}.sql": "select 1 as x\n",
                "dbt/models/daily.sql": "select * from {{ ref('MODEL') }}\n".replace("MODEL", OLD_MODEL),
            },
            delete=[f"dbt/models/{OLD_MODEL}.sql"],
        ),
        Case(
            "Airflow task removed, docs still name it",
            "removed-names",
            False,
            committed={"airflow/dags/pipeline.py": f'TASKS = dict(task_id="{OLD_TASK}")\n', "docs/guide.md": f"Rerun `{OLD_TASK}`.\n"},
            files={"airflow/dags/pipeline.py": "TASKS: dict[str, str] = {}\n"},
        ),
        Case(
            "dependency removed, still imported",
            "removed-names",
            False,
            committed={"requirements_dev.txt": "wfdb==4.3.1\n", "scripts/tool.py": "import wfdb\n"},
            files={"requirements_dev.txt": "pytest==9.1.1\n"},
        ),
        Case("unused function", "unused-code", False, {"scripts/tool.py": f"def {UNUSED_FUNCTION}() -> int:\n    return 1\n"}, expect_warning=True),
        Case(
            "declared dependency nobody imports",
            "unused-dependencies",
            False,
            {"requirements_dev.txt": "wfdb==4.3.1\n", "scripts/tool.py": "import json\n\nX = json.dumps({})\n"},
            expect_warning=True,
        ),
        Case("file nothing references", "orphan-files", False, {ORPHAN_DOC: "Nobody links here.\n"}, expect_warning=True),
        Case(
            "lock matches its source",
            "requirement-locks",
            True,
            {
                "services/app/requirements.in": "requests==2.33.1\n",
                "services/app/requirements.txt": "requests==2.33.1 \\\n    --hash=sha256:" + "0" * 64 + "\n",
            },
        ),
        Case("lock missing for a source", "requirement-locks", False, {"services/app/requirements.in": "requests==2.33.1\n"}),
        Case(
            "lock out of date",
            "requirement-locks",
            False,
            {
                "services/app/requirements.in": "requests==2.33.1\n",
                "services/app/requirements.txt": "requests==2.32.0 \\\n    --hash=sha256:" + "0" * 64 + "\n",
            },
        ),
        Case(
            "documented variable nothing reads",
            "env-example-unused",
            False,
            {".env.example": f"AWS_REGION=\n{UNUSED_SETTING}=\n", "scripts/tool.py": "import os\n\nNAME = " + ENVIRON + '.get("AWS_REGION", "")\n'},
            expect_warning=True,
        ),
        Case("duplicate Markdown headings", "markdownlint", False, {"docs/guide.md": GOOD_DOC + "\n## Setup\n\nText.\n\n## Setup\n\nText.\n"}),
    ]
)

BLOCK_REASONS = {
    "missing document metadata": "no front matter",
    "README-like guide metadata": "no front matter",
    "metadata title mismatch": "title does not match",
    "invalid metadata date": "last_updated",
    "metadata timestamp rejected": "last_updated",
    "writing conjunction": "docs/guide.md:11: comma before a final",
    "writing time word": "docs/guide.md:11: time-bound word",
    "duplicate Markdown headings": "MD024",
    "GitHub token": "leaks found: 1",
    ".env": ".env: credential or state file staged",
    "Terraform state": "infra/terraform.tfstate: credential or state file staged",
    "Terraform state backup": "infra/bootstrap/terraform.tfstate.1789700741.backup: credential or state file staged",
    "private key file": "keys/deploy.pem: credential or state file staged",
    "CSV outside declared folders": "data/patients.csv: data file outside the declared folders",
    "file over 5 MB": "docs/big.bin: 5,242,881 bytes, over the 5 MB limit",
    "S603 outside the launcher": "scripts/tool.py:1: suppression comment not in the approved list",
    "blanket noqa": "scripts/tool.py:1: suppression comment not in the approved list",
    "type ignore": "scripts/tool.py:1: suppression comment not in the approved list",
    "subprocess import": "scripts/tool.py:1: subprocess imported outside the process launcher",
    "Ruff rule family removed": "pyproject.toml: Ruff rule families missing from select: S",
    "Ruff ignore added": "pyproject.toml: Ruff loosening keys present: ignore",
    "Ruff line length raised": "pyproject.toml: Ruff line-length is 200, not 160",
    "MyPy exclude added": "pyproject.toml: MyPy excludes added: ^services/",
    "MyPy error code disabled": "pyproject.toml: MyPy settings that can loosen checks: disable_error_code",
    "unused Terraform variable": "terraform_unused_declarations",
    "SSH open to the internet": "CKV_AWS_24",
    "upper-case SQL keywords": "CP01",
    "SQL noqa comment": "dbt/models/sample.sql:1: suppression comment not in the approved list",
    "SQLFluff rule excluded": ".sqlfluff: SQLFluff loosening keys present: exclude_rules",
    "SQLFluff templater changed": ".sqlfluff: [sqlfluff] templater must be dbt",
    "checkov skip added": ".checkov.yaml: checkov rules skipped without approval: CKV_AWS_24",
    "home path": "notes.md:1: home-directory path with a user name",
    "temp path": "notes.md:1: machine temporary path",
    "personal email": "notes.md:1: email address",
    "phone number": "notes.md:1: phone number",
    "AWS account ARN": "infra/policy.json:1: AWS account ID",
    "value declared in .env": "scripts/deploy.sh:1: value declared in .env",
    "bucket named after the project": "docs/notes.md:1: value declared in .env",
    "allowlist entry without reason": ".privacy_allowlist:1: allowlist entry without a reason",
    "undocumented variable": "scripts/tool.py:3: NEW_SETTING is read but not in .env.example",
    "script removed, docs still name it": f"docs/guide.md:1: {OLD_TOOL}.py was removed but is still referenced",
    "flag removed, docs still name it": "docs/guide.md:1: --legacy-mode was removed but is still referenced",
    "function removed, code still calls it": f"scripts/use.py:1: {OLD_FUNCTION} was removed but is still referenced",
    "Terraform variable removed, still referenced": f"infra/main.tf:2: {OLD_VARIABLE} was removed but is still referenced",
    "dbt model removed, still referenced": f"dbt/models/daily.sql:1: {OLD_MODEL} was removed but is still referenced",
    "Airflow task removed, docs still name it": f"docs/guide.md:1: {OLD_TASK} was removed but is still referenced",
    "dependency removed, still imported": "scripts/tool.py:1: wfdb was removed but is still referenced",
    "cleanup allowlist entry without reason": ".cleanup_allowlist:1: allowlist entry without a reason",
    "unused function": f"scripts/tool.py:1: unused function '{UNUSED_FUNCTION}'",
    "declared dependency nobody imports": "requirements_dev.txt: wfdb is declared but nothing imports it",
    "file nothing references": f"{ORPHAN_DOC}: no other tracked file references it",
    "lock missing for a source": "services/app/requirements.in: no hash-pinned requirements.txt beside it",
    "lock out of date": "services/app/requirements.txt: requests==2.33.1 from requirements.in is not pinned with hashes",
    "documented variable nothing reads": f".env.example:2: {UNUSED_SETTING} is documented but nothing reads it",
    "untyped subject": "commit message: subject is not a Conventional Commit",
    "missing space after colon": "commit message: subject is not a Conventional Commit",
    "unknown type": "commit message: subject is not a Conventional Commit",
    "empty description": "commit message: subject is not a Conventional Commit",
    "agent credit trailer": "commit message:5: AI attribution",
    "agent credit, lower case": "commit message:3: AI attribution",
    "vendor address only": "commit message:3: AI attribution",
    "generated-with line": "commit message:3: AI attribution",
    "agent session trailer": "commit message:3: AI attribution",
    "assisted-by credit": "commit message:3: AI attribution",
    "scissors cannot hide actual credit": "commit message:4: AI attribution",
}


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
    write(repo, {".gitignore": "/.documentation_review.json\n"})
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
        args = ["run", case.hook, *(["--verbose"] if case.expect_warning else [])]  # pre-commit hides passing output
        if case.message is not None:
            message = repo / ".git" / "COMMIT_EDITMSG"
            message.write_text(case.message)
            args += ["--hook-stage", "commit-msg", "--commit-msg-filename", str(message)]
        result = run_command(str(PRE_COMMIT), args, cwd=repo, timeout=300)
        output = result.stdout + result.stderr
        passes = case.expect_pass or case.expect_warning
        ok = (result.returncode == 0) == passes and "Traceback (most recent call last)" not in output
        if not case.expect_pass:
            reason = BLOCK_REASONS.get(case.name, "<no declared reason>")
            ok = ok and reason in output and (not case.expect_warning or f"warning: {reason}" in output)
        return ok, output


def review_all(repo: Path) -> None:
    """Draft and complete the local documentation review record for the scratch repository's staged snapshot."""
    python = str(ROOT / ".venv" / "bin" / "python")
    run_command(
        python,
        ["-m", "tools.documentation_review", "prepare", "--reviewer", "check test", "--reviewed-at", "2026-09-28T00:00:00Z", "--refresh"],
        cwd=repo,
        check=True,
    )
    record_path = repo / ".documentation_review.json"
    record = json.loads(record_path.read_text())
    for item in record["documents"]:
        item["outcome"] = "current"
        item["notes"] = "Checked against the scratch repository."
    record_path.write_text(json.dumps(record, indent=2) + "\n")


def run_documentation_review_cases() -> list[tuple[str, bool, str]]:
    """Exercise the documentation-review hook: missing, pending, complete, stale and untracked evidence."""
    results = []
    python = str(ROOT / ".venv" / "bin" / "python")
    with tempfile.TemporaryDirectory(prefix="repo_documentation_review_") as scratch:
        repo = scratch_repo(Path(scratch), Case("review setup", "documentation-review", True, committed={"docs/guide.md": "Guide.\n"}))

        def hook() -> tuple[int, str]:
            result = run_command(str(PRE_COMMIT), ["run", "documentation-review"], cwd=repo, timeout=300)
            return result.returncode, result.stdout + result.stderr

        write(repo, {"docs/guide.md": "Guide, revised.\n"})
        git(repo, "add", "docs/guide.md")
        code, output = hook()
        results.append(("no review record", code != 0 and "BLOCK" in output, output))
        run_command(
            python, ["-m", "tools.documentation_review", "prepare", "--reviewer", "check test", "--reviewed-at", "2026-09-28T00:00:00Z"], cwd=repo, check=True
        )
        code, output = hook()
        results.append(("pending outcomes", code != 0 and "review unresolved" in output, output))
        review_all(repo)
        code, output = hook()
        results.append(("complete review", code == 0, output))
        write(repo, {"docs/guide.md": "Guide, changed after review.\n"})
        git(repo, "add", "docs/guide.md")
        code, output = hook()
        results.append(("document changed after review", code != 0 and "BLOCK" in output, output))
        review_all(repo)
        write(repo, {"docs/new.md": "Unstaged new document.\n"})
        code, output = hook()
        results.append(("untracked document", code != 0 and "untracked documentation" in output, output))
        (repo / "docs" / "new.md").unlink()
        ci = run_command(str(PRE_COMMIT), ["run", "--hook-stage", "manual", "--verbose", "documentation-review-untracked"], cwd=repo, timeout=300)
        results.append(("CI stage: record untracked", ci.returncode == 0 and "record untracked and ignored" in ci.stdout + ci.stderr, ci.stdout + ci.stderr))
        git(repo, "add", "-f", ".documentation_review.json")
        code, output = hook()
        results.append(("tracked record", code != 0 and "review evidence must stay local" in output, output))
    return results


def run_range_case() -> tuple[bool, str]:
    """Exercise CI's range entry point on full stored messages, including credit after a scissors line."""
    with tempfile.TemporaryDirectory(prefix="repo_commit_range_") as scratch:
        repo = scratch_repo(Path(scratch), Case("range setup", "commit-msg", True))
        base = git(repo, "rev-parse", "HEAD").strip()
        python = str(ROOT / ".venv" / "bin" / "python")
        check = ["-m", "scripts.check_commit_message", "--range"]
        git(repo, "commit", "--allow-empty", "-qm", f"fix: human credit\n\n{CREDIT}: Jane Doe <jane@example.invalid>")
        good = run_command(python, [*check, f"{base}..HEAD"], cwd=repo)
        git(repo, "commit", "--allow-empty", "-qm", f"fix: bad credit\n\n{SCISSORS}\n{CREDIT}: Claude <{VENDOR_ADDRESS}>")
        bad = run_command(python, [*check, f"{base}..HEAD"], cwd=repo)
        missing = run_command(python, [*check, "missing-ref..HEAD"], cwd=repo)
        ok = good.returncode == 0 and bad.returncode == 1 and "AI attribution" in bad.stderr and missing.returncode != 0
        return ok, f"clean range exit={good.returncode}; attributed range exit={bad.returncode}; missing revision exit={missing.returncode}\n"


def run_privacy_scope_case() -> tuple[bool, str]:
    """Ignored files are skipped by default and scanned with --all; --warn reports but exits 0; values never print."""
    with tempfile.TemporaryDirectory(prefix="repo_privacy_scope_") as scratch:
        repo = scratch_repo(Path(scratch), Case("privacy setup", "privacy-scan", True))
        (repo / ".git" / "info" / "exclude").write_text(".venv\n.tools\nlocal_notes.md\n")
        write(repo, {"local_notes.md": f"Log at {HOME_PATH}\n"})
        python = str(ROOT / ".venv" / "bin" / "python")
        scan = ["-m", "tools.repo_checks", "privacy-scan"]
        default = run_command(python, scan, cwd=repo)
        full = run_command(python, [*scan, "--all"], cwd=repo)
        warned = run_command(python, [*scan, "--all", "--warn"], cwd=repo)
        marker = "local_notes.md:1: home-directory path with a user name"
        leaked = HOME_PATH in full.stderr + warned.stderr
        ok = default.returncode == 0 and full.returncode == 1 and marker in full.stderr and warned.returncode == 0 and "warning: " in warned.stderr
        ok = ok and not leaked
        return ok, f"default exit={default.returncode}; --all exit={full.returncode}; --warn exit={warned.returncode}; value leaked={leaked}\n"


def run_hook_case() -> tuple[bool, str]:
    """Commit through the repository's .githooks so the installed hooks, not only pre-commit run, are proven."""
    with tempfile.TemporaryDirectory(prefix="repo_git_hooks_") as scratch:
        repo = scratch_repo(Path(scratch), Case("hook setup", "commit-msg", True))
        shutil.copytree(ROOT / ".githooks", repo / ".githooks")
        git(repo, "config", "core.hooksPath", ".githooks")
        write(repo, {"notes.md": GOOD_DOC + "\nA clean change.\n"})
        git(repo, "add", "notes.md")
        review_all(repo)
        good = run_command("git", ["commit", "-qm", "docs: add notes"], cwd=repo, timeout=300)
        write(repo, {"notes.md": GOOD_DOC + "\nA second change.\n"})
        git(repo, "add", "notes.md")
        review_all(repo)
        bad = run_command("git", ["commit", "-qm", f"docs: more notes\n\n{CREDIT}: Claude <{VENDOR_ADDRESS}>"], cwd=repo, timeout=300)
        write(repo, {".env": "REGION=us-west-2\n"})
        git(repo, "add", "-f", ".env")
        review_all(repo)
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
    for label, ok, output in run_documentation_review_cases():
        count += 1
        failures += not ok
        sys.stdout.write(f"{'ok' if ok else 'WRONG':<6} {'documentation-review':<19} {label}\n")
        if not ok:
            sys.stdout.write("".join(f"       {line}\n" for line in output.strip().splitlines()[-8:]))
    for label, runner in (("commit-range", run_range_case), ("privacy scope", run_privacy_scope_case), ("git hooks", run_hook_case)):
        ok, output = runner()
        count += 1
        failures += not ok
        sys.stdout.write(f"{'ok' if ok else 'WRONG':<6} {label:<19} integrated Git checks\n       {output}")
    sys.stdout.write(f"{count - failures} of {count} cases behaved as expected\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
